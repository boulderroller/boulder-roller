# Boulder Roller Math Audit - 2026-07-09

Bead: `boulderroller-v2-ymre`

> Historical independent pass. See
> `docs/design/MATH_AUDIT_PHASE2_2026-07-12.md` for the current correction ledger,
> lifecycle findings, and remediation order. In particular, the primary portal now reads
> the indexed on-chain leaderboard order; the open tie defect is the missing ratified
> pooled-tie rule, not a separate current display-versus-payer order.

Scope: protocol arithmetic, backend ride and climb economics, workout parser
metrics, climb detection and signature matching, mobile GPS recording math, and
portal/backend token amount boundaries. This audit excludes archived design
prototype UI code except where the same math pattern still exists in live code.

## Final remediation outcome - 2026-07-18

The launch-critical findings from this audit and Phase 2 are remediated and the
composed math seaworthiness gate is closed. The final integration preserved
program ABI order through `0x44`; passed 97 Rust unit tests, 20 full
local-validator scenarios, 1,568 broad backend cases with the three inherited
missing-Supabase fixtures explicitly deselected, PostgreSQL 17 migration/runtime
proof, and the exact portal/mobile/BoulderScan amount gates.

The exact release `dc398fbbd541c305374f33a0cdea1bef99efd832` applied migration
137 and passed all 27 deployed schema requirements. On devnet, Vault 16 used a
durably prepared 437-byte v0 settlement, distributed Settlement Week 131,
withdrew exactly `100000000000000` LP base units, harvested its DUNG claim, and
finished with no live position or unclaimed reward. This closes the audit's
first-cohort money-path gate; it does not ratify the separate mainnet ceremony
or the remaining P2 canon research.

## Executive summary

Boulder Roller has several solid math decisions already in place: CAL base units
are separated from display units in the ride effort policy, route-only rides are
kept out of live economics, settlement tests assert bucket-local DUNG
conservation, and the Rust workout parser has a much better Normalized Power
implementation than the older Python compatibility paths.

The main critique is that the program does not yet have one complete math
authority per domain. Some high-value arithmetic is still split across protocol,
backend, and UI surfaces. The riskiest examples are:

1. Settlement bucket arithmetic violates the repo's own u128-intermediate
   decision and can overflow before supply-cap checks run.
2. The on-chain Record Board accepts positive completion times even when the DB
   validation layer rejects the same time.
3. Displayed leaderboard rank and paid Record Board rank use different tie
   rules.
4. Late rides can still earn CAL but miss climb completion, tribute, and Record
   Board writes because the CAL age window and settlement window disagree.
5. Per-ride CAL tribute is not conserved across multiple climb completions.
6. Staker settlement fairness depends on a complete backend-supplied account
   list.
7. Portfolio, LP withdrawal, and ledger paths still cross float/display-unit
   boundaries before exact economic decisions.
8. Climb matching still has v1 hash similarity and v2 DCT similarity in active
   paths.

The rest of this audit ranks those findings, then inventories the math surfaces
that were checked.

## Ranked findings

### P0 - DUNG settlement share math can overflow before cap checks

Follow-up bead: `boulderroller-v2-2l9f`

Evidence:

- `docs/design/V4B_OPEN_QUESTIONS_RESOLUTION.md` Q-D2 explicitly resolves to
  "Use `u128` intermediates for all bucket-share computations."
- `protocol/anchor/Cargo.toml` enables release overflow checks.
- `protocol/anchor/programs/boulder_rollers/src/lib.rs` still computes
  settlement buckets with direct `u64 * u64` products:
  - `total_dung * config.staker_share_bps`
  - `leaderboard_total * rank_pct`
  - `staker_total * unlock_pct`

Why this matters:

`MAX_SUPPLY` is around `1_000_000_000 * 10^9`, or about `1e18`. Multiplying a
near-cap DUNG amount by `10_000` bps exceeds `u64::MAX`. Since supply-cap checks
happen after the amount is calculated, the program can panic/abort before the
intended cap guard or carry logic runs.

Critique:

The conservation tests are checking the right economic model, but they use
Python integers and do not prove the Anchor arithmetic width. This is a direct
implementation mismatch with the already-ratified design decision.

Required outcome:

Use checked `u128` intermediates for every settlement share calculation, then
cast back only after bounds are proven. Add a red-green protocol or source-gate
test near the DUNG cap that fails on the current direct `u64` multiplication and
passes after the fix.

### P1 - On-chain Record Board accepts times that DB validation rejects

Follow-up bead: `boulderroller-v2-rbvd`

Evidence:

- `backend/sql/050_tiebreaker.sql:49-69` enforces DB leaderboard time bounds
  through hard exceptions.
- `backend/app/services/climb_economy_processor.py:275-285` records the DB
  completion and reads `completion_validated`.
- `backend/app/services/climb_economy_processor.py:293-318` still calls
  `ride_executor.record_climb_completion(...)` regardless of
  `completion_validated`.
- `backend/app/services/climb_economy_processor.py:360-369` logs "skipped rank
  projection" for invalid times only after the chain write has already run.
- `protocol/anchor/programs/boulder_rollers/src/lib.rs:665-725` only requires
  `completion_time_s > 0`, then updates the rider's PB, vault KOM, and
  `VaultLeaderboard`.

Why this matters:

The DB layer is the layer with the physics/time validation. The chain is the
layer that pays the permanent Record Board. Right now an invalid-but-positive
time can skip the displayed SQL leaderboard projection while still entering the
paid on-chain leaderboard.

Critique:

This is the sharpest example of validation living on the layer that does not pay
money. The issue is not that the DB function lacks checks; it has them. The
issue is that the backend continues into the on-chain money write after a failed
or unvalidated DB completion.

Required outcome:

Do not call `record_climb_completion` for a completion that fails validation, or
move the same validation predicate into the chain-side instruction/account
contract. Add a red-green test where a DB-invalid completion currently reaches
`ride_executor.record_climb_completion` and after the fix does not.

### P1 - Displayed rank and paid rank disagree on ties

Follow-up bead: `boulderroller-v2-rtie`

Evidence:

- `backend/sql/050_tiebreaker.sql:1-4` documents the DB rule: first achiever
  wins.
- `backend/sql/050_tiebreaker.sql:96-103` ranks equal times by earlier
  `achieved_at`.
- `protocol/anchor/programs/boulder_rollers/src/lib.rs:4559-4585` updates the
  on-chain leaderboard with `sort_by_key(|e| e.time_s)` only.
- `protocol/anchor/programs/boulder_rollers/src/lib.rs:2887-2888` pays the
  Record Royalty bucket by array position using `LEADERBOARD_RANK_PCTS[i]`.

Why this matters:

Times are stored as whole seconds. Ties on short climbs are not edge cases. A
rider can see one rank in the DB-backed app surface while the chain pays a
different rank forever for the same board.

Critique:

Stable insertion order is not a product rule. The DB has an explicit tie rule,
but the payer does not. This is duplicate math where the less explicit copy is
the authoritative money path.

Required outcome:

Define one Record Board tie policy across DB, indexer/API, and chain. Either port
first-achiever-wins on-chain, or deliberately split tied ranks' payout shares.
Add a test with equal whole-second times that proves displayed order and paid
order match.

### P1 - Late rides can earn CAL while climb completions vanish

Follow-up bead: `boulderroller-v2-lrwd`

Resolution (2026-07-14): `boulderroller-v2-lrwd` landed the ratified lifetime
tribute flow. The canonical receipt-backed completion instruction now accepts
every ride that passes the 30-day economic age guard, preserves original
`completed_at`/economic epoch provenance, and credits the Vault's oldest open
Settlement Week after empty-week catch-up. The backend completion-before-CAL
coordinator keeps chain failures retryable instead of silently minting CAL
first. The evidence below describes the pre-fix state. Admission is frozen at
`RideAttestation.settled_at`, aggregate latest-completion time cannot regress on
delayed arrival, and the replayable receipt-less legacy completion instruction
fails closed. Exact delayed-ride
`finalized_at` projection remains separate under `boulderroller-v2-4x3v`; it
must bind the flow actually credited rather than infer one from the historical
ride week. Disabled legacy client and smoke paths are retired separately under
`boulderroller-v2-29rm`.

Evidence:

- `backend/app/services/ride_effort_policy.py:37-39` allows automatic economics
  for rides up to 30 days old.
- `protocol/anchor/programs/boulder_rollers/src/lib.rs:4313-4336` only credits
  tribute to the vault's open settlement week or the next week.
- `protocol/anchor/programs/boulder_rollers/src/lib.rs:727-738` calls
  `credit_tribute_for_week(...)` from `record_climb_completion`.
- `backend/app/services/climb_economy_processor.py:226-227` catches the
  resulting climb/vault exception as a generic warning and continues the climb
  loop.

Why this matters:

A Strava backfill, delayed Garmin sync, or processing backlog can be accepted by
the CAL policy while the associated climb completion, tribute, and Record Board
write are rejected by the settlement-week policy. For a permanent board, a PB
uploaded ten days late being dropped silently is a product/economy bug, not just
a logging issue.

Critique:

Each local policy is defensible in isolation. The composition is not. The system
has two answers to the same question: "how late can an economically relevant ride
arrive?"

Required outcome:

Unify the late-ride policy. Accepted CAL rides need a deterministic climb policy:
backfill into a safe bucket, record no-tribute completions with rider-visible
status, route to review, or reject CAL consistently. The implementation must not
silently drop the completion side while keeping the ride's CAL side.

### P1 - CAL tribute is not conserved at the ride level

Follow-up bead: `boulderroller-v2-zxoz`

Evidence:

- `backend/app/services/climb_economy_processor.py` computes each climb's
  tribute as:
  `cal_earned * min(climb.time_s / total_ride_duration_s, 1.0) * intensity`.
- The intensity multiplier can be `1.3`, `1.2`, `1.0`, or `0.8`.
- `protocol/anchor/programs/boulder_rollers/src/lib.rs::record_climb_completion`
  accepts each `cal_tribute` independently, records a receipt per ride/vault,
  increments `completion.total_cal_tributed`, increments
  `vault.total_cal_burned`, and credits the vault's weekly tribute.
- `credit_cal` proves a ride mints exactly the attested CAL amount, but there is
  no on-chain aggregate check that all climb completion tribute for that ride is
  `<= ride_attestation.cal_earned`.

Concrete failure shape:

A one-hour ride with two thirty-minute climbs at `>= 10%` grade tributes
`50% * 1.3 = 65%` of ride CAL to each vault. Total tribute becomes `130%` of
the ride's earned CAL.

Critique:

The chain is trusting the backend for a value that is economically derived from
the ride. Receipts prevent duplicate ride/vault completions, but they do not
conserve the ride's total CAL budget across all vaults. If the intent is
"tribute is a bounded allocation of earned CAL", the current math breaks that
invariant. If the intent is "tribute is independent score credit", then the
field names and downstream burn/reward language need to stop implying
conservation.

Required outcome:

Define the invariant first. If tribute is bounded by earned CAL, normalize or
cap per-ride tribute across all matched vaults before writing completions, and
add a red-green test using the two-steep-half-climbs example.

Additional duplicate-authority finding (2026-07-15):
`PatternEngine._match_vaults_and_record` independently estimates a per-climb
tribute preview from climb vertical instead of carrying the frozen ride-level
allocation. Pattern results, replay, or NATS consumers can therefore expose a
different amount from the authoritative plan and chain. Follow-up bead
`boulderroller-v2-qv7p` removes that preview formula or supplies the exact
allocation after ride-level apportionment.

### P1 - Rewardable TSS can be inflated by self-reported FTP

Follow-up bead: `boulderroller-v2-ftpv`

Evidence:

- The production basic-profile selector omitted `ftp_w`, so normal ingestion
  happened to fall back to 200 W even though route tests supplied mocked FTP.
- `RideIngestJob.user_ftp_w` was still an unverified queue input and became the
  live denominator whenever a producer supplied it.
- `backend/app/services/ride_metrics.py:262-272` computes power TSS with
  `IF = normalized_power / ftp`, so TSS scales with `1 / ftp^2`.
- Fixing the production selector alone would therefore have activated the
  rider-controlled denominator the audit anticipated.
- The audit did not find an authoritative reward clamp, verification source, or
  floor on profile FTP before rewardable CAL is derived from TSS.

Why this matters:

Lowering profile FTP increases TSS and therefore CAL for the same power file. If
profile FTP is rider-editable, rewardable CAL has a self-report denominator.

Critique:

The policy layer correctly separates route-only estimates from rewardable rides,
but it does not by itself make the power denominator trustworthy. Sensor-backed
power is only one side of the formula; FTP authority is the other.

Required outcome:

Define rewardable FTP authority separately from display/profile FTP. Clamp,
verify, snapshot, or review FTP changes before they affect rewardable TSS/CAL,
and add a test proving the same power stream cannot mint materially different
CAL through an arbitrary profile FTP edit.

Resolution landed 2026-07-14:

- Implementation commit `9f97a5a92c3987d7d36b617cb01dde50f46f94e4`
  separates mutable training/display FTP from immutable reward FTP.
- New rides use a neutral 200 W economic default or an append-only
  service-verified authority effective at the ride's `started_at`; verified
  changes cannot activate before the next Monday 12:00 UTC boundary.
- Rides persist separate `tss` and `economic_tss`, and frozen plans commit the
  reward FTP value, source, authority row, and policy version in their evidence
  hash. Historical unknowns remain NULL rather than being retroactively
  described as verified.
- Red-green and PostgreSQL runtime tests prove profile FTP 50 versus 500 cannot
  move CAL, late rides select the ride-time authority, one-time bindings and
  economic TSS cannot mutate, and only the service role can invoke authority
  functions.

Deployment resolution landed 2026-07-14:

- Live read-only preflight found that the active PostgreSQL 17 project exposes
  pgcrypto under `extensions`, not `public`, while `pg_catalog.sha256(bytea)` is
  available independently of the extension schema.
- Implementation commit `6267976e` removes the nonexistent `public.digest`
  dependency and uses the PostgreSQL 17 built-in SHA-256 function.
- The red PostgreSQL proof failed at authority registration with
  `UndefinedFunction`. The unchanged green proof relocates pgcrypto outside
  `public`, applies the migration twice, registers an authority, and matches the
  stored 32-byte evidence hash to the expected SHA-256 digest. The broader FTP
  authority gate remains green at 68 tests.

### P1 - Staker settlement depends on complete off-chain enumeration

Follow-up bead: `boulderroller-v2-9su7`

Evidence:

- `distribute_epoch_rewards` gathers `VaultStake` accounts from
  `ctx.remaining_accounts.iter().skip(remaining_idx)`.
- It filters the accounts that were passed, sums `total_lp` over only that set,
  and distributes unlocked staker DUNG pro rata across only that set.
- The tests cover bucket-local conservation and a one-staker happy path, but not
  omitted eligible stake accounts.

Why this matters:

If the backend omits one eligible staker PDA, conservation still passes: the
staker bucket is distributed/carries correctly over the passed set. Fairness
does not pass: the denominator is too small, included stakers get too much, and
the omitted staker gets nothing.

Critique:

This is the classic difference between accounting conservation and recipient
set completeness. The tests prove the bucket does not leak DUNG; they do not
prove the bucket paid the right people.

Required outcome:

Add an explicit completeness gate. Options include a backend gate that compares
the passed stake PDAs to an indexed expected set, an on-chain accumulator, or a
pagination design that makes completeness provable. Add a test that omits one
valid eligible stake and fails instead of silently redistributing.

### P1 - Portfolio lifecycle mixes human token amounts with base units

Follow-up bead: `boulderroller-v2-d2df`

Evidence:

- `backend/app/solana_direct.py::get_cal_balance` returns a human-readable
  float: `int(balance.value.amount) / 10^CAL_SPL_DECIMALS`.
- `backend/app/routes/portfolio.py::_build_balance_lifecycle_view` passes that
  value through `_to_balance_units`, which currently returns `int(amount)`.
- The result is assigned to `BalanceTokenState.balance_base_units`.
- `backend/app/services/balance_lifecycle.py` treats `balance_base_units` as an
  exact base-unit amount when checking insufficient balance.
- `web/portal/src/pages/Portfolio.tsx::decimalToBaseUnits` parses with
  `BigInt`, but then rejects amounts above `Number.MAX_SAFE_INTEGER` and returns
  `Number(raw)`.

Concrete failure shape:

An on-chain balance of `100 CAL` is read as human `100.0`. The lifecycle builder
can label that as `100` base units instead of `100_000_000_000` base units.
That can make a valid rider balance look insufficient to the portfolio lifecycle
planner. The transaction builder appears to reread token accounts for actual
transaction construction, so this is most likely a rider-facing/action-planning
bug rather than direct token loss, but the unit contract is still wrong.

Critique:

Token math should have one rule: base units stay exact across API/action
boundaries; decimal display is derived at the edge. The current path has a
field named base units receiving human floats, and the portal action path cannot
carry large base-unit values without `Number` limits.

Required outcome:

Standardize API payloads and action contracts on base-unit strings or another
bigint-safe representation. Keep human display numbers out of transaction and
balance-lifecycle decisions. Add tests for 9-decimal CAL balances and values
above JS safe integer range.

### P1 - Economic ledger hash chain is not atomic and crosses float storage

Follow-up bead: `boulderroller-v2-ehsh`

Evidence:

- `backend/app/services/economic_ledger.py:66-94` computes the hash from
  string-encoded `Decimal` amounts and balances.
- `backend/app/services/economic_ledger.py:195-205` reads the previous
  wallet/denomination event and computes `balance_after` in application code.
- `backend/app/services/economic_ledger.py:219-225` inserts `amount` and
  `balance_after` as `float(...)`.
- `backend/app/services/economic_ledger.py:249-254` performs the insert as a
  separate Supabase table write, with no visible row lock or database-side
  append function in this checkout.
- No SQL migration defining `economic_events` or an atomic append RPC was found
  under `backend/sql`.

Why this matters:

Two concurrent writes for the same wallet/denomination can read the same
previous event, compute the same previous hash, and fork the chain. Separately,
the stored numeric values can lose exactness even though the event hash was
computed from exact `Decimal` strings.

Critique:

The hash-chain idea is good, but the atomicity claim in the docstring is not
implemented by the visible code. A tamper-evident ledger needs the database write
boundary to preserve both order and exact numeric representation.

Required outcome:

Move ledger append into a database function or transaction that locks the
wallet/denomination stream, stores exact numeric/base-unit strings or NUMERIC
values, and computes/stores the hash from the same canonical representation that
will be verified later. Add a race test with two concurrent events.

Resolution landed 2026-07-14:

- Implementation commit `d7fbf860` replaces the application read/float/insert
  sequence with one service-owned PostgreSQL append function.
- The function accepts canonical decimal text, serializes each
  wallet/denomination stream with a transaction advisory lock, derives the
  running balance in exact `NUMERIC`, and computes the scale-neutral v2 hash from
  the same values it stores. Existing rows retain their v1 hashes and legacy NULL
  pipeline provenance.
- RLS plus explicit grants remove direct rider and service-role table writes; new
  events require pipeline provenance and enter only through the service RPC.
- Red evidence covered missing exact/hash APIs and the deployed immutability
  trigger blocking the first migration design. Green PostgreSQL evidence covers
  migration idempotence, legacy preservation, exact
  `9007199254740993.000000001` plus 9-decimal dust, the shared decimal bound,
  denied direct writes, Python/SQL hash parity, and eight concurrent appends with
  balances 1 through 8 and an unbroken hash chain.

### P2 - LP stake accounting is only proven in the 1:1 pool case

Follow-up bead: `boulderroller-v2-hba4`

Evidence:

- `stake_cal_in_vault` and `deposit_cal_from_balance` mint LP as:
  `amount * total_lp_supply / total_cal_staked` with checked `u128`
  intermediates.
- `unstake_cal_from_vault` and `withdraw_cal_to_balance` return CAL as:
  `lp_amount * total_cal_staked / total_lp_supply`.
- The code then subtracts `cal_to_return` from both `vault.total_cal_staked`
  and `stake.cal_staked`.
- The protocol truth test covers a happy path where pool ratio remains 1:1.

Critique:

The pro-rata LP math itself is the right shape and uses appropriate width. The
under-specified part is `stake.cal_staked`: is it principal deposited, current
pool-share accounting, or display-only historical principal? Updating it by
pro-rata `cal_to_return` only remains obviously correct while the vault ratio
stays 1:1. Floor dust, donations, future fee/reward behavior, or any non-1:1
ratio need explicit tests. `lp_to_mint > 0` is also not asserted, so extreme
ratios can theoretically accept a deposit that mints zero LP.

Required outcome:

Define `stake.cal_staked` semantics and add invariant tests for non-1:1 ratios,
floor dust, full exit, partial exit, and exit-fee effects. Add a zero-LP mint
guard if deposits can ever hit that floor.

Remediation outcome (2026-07-17): `VaultStake.cal_staked` is now remaining
deposited-principal basis, while `VaultStake.lp_tokens` is the recorded
pool-share accounting authority.
Both withdrawal handlers share one checked transition: gross CAL and the 50 bps
fee are calculated from the pool share, retained principal is floored on the
remaining position LP, and full exit clears it exactly. Inconsistent one-sided
pool inventory and zero-output deposits fail before token movement. Red-to-green
tests cover ratios above and below 1:1, dust, zero-value pools, invalid
inventory, u64 boundaries, and bounded exhaustive conservation. Backend and
indexer active-position reads now key on positive LP, preserving a redeemable
position even when retained principal floors to zero.

### P1 - Identity-bound VaultStake accounting can drift from SPL LP custody

Follow-up bead: `boulderroller-v2-ypn8a` (`agent-autonomous` after ratification)

Evidence:

- Each Vault LP mint is a standard SPL Token mint. The Vault PDA is its mint and
  freeze authority, but the program never freezes or thaws LP token accounts.
- Principal, current LP, rewards, and weekly LP snapshots remain in the
  rider-and-Vault-bound `VaultStake` PDA; SPL transfers do not move that state.
- Direct-wallet deposit accepts an unconstrained LP token account. `mint_to`
  enforces the LP mint, but it does not require the destination to belong to the
  rider whose `VaultStake` is credited.
- Withdrawal requires both that identity-bound `VaultStake` and LP tokens a
  matching signer can burn. Receiving transferred LP does not transfer the
  corresponding principal, snapshot, or reward rights.

Why this matters:

A custom deposit destination or ordinary post-deposit SPL transfer can split
token custody from the accounting record. The recipient cannot redeem the
sender's position, while the original rider may no longer hold the LP required
to withdraw. Settlement weight remains with the original `VaultStake`. This
does not authorize theft, but it can strand redemption and makes the word
"redeemable" conditional on an unstated no-transfer rule.

Required outcome:

Ratify one model before implementation: either LP is a non-transferable,
identity-bound position receipt, or LP is genuinely bearer and principal,
rewards, and snapshot ownership move with it. Enforce the chosen custody model
for direct-wallet and Boulder Roller Balance paths, and migrate or quarantine
existing devnet accounts with validator proof.

Ratified outcome (2026-07-17): the core product is one account-bound,
non-transferable position. Wallet and Boulder Roller Balance actions converge on
one deterministic rider-and-Vault LP custody account whose token authority is
the `VaultStake` PDA and which the Vault freezes between instructions. Internal
LP amount and `VaultStake.lp_tokens` must match exactly before movement. Legacy
wallet, custom-destination, Balance, split, or mismatched custody is restored or
quarantined without rewriting principal, rewards, or weekly snapshots. Future
composability is preserved at a separate boundary: an explicitly integrated
program identity may own a position and issue its own bearer shares; core LP is
not made transferable.

Remediation outcome (2026-07-17): program ABI `0x43` derives one
`vault_position_lp` PDA for both funding paths, makes `VaultStake` its token
authority, thaws only around an atomic mint or burn, and refreezes before
returning. Backend preparation reads the custody account and LP mint in one RPC
snapshot and fails closed unless the amount equals `VaultStake.lp_tokens`, the
account is frozen, and the Vault remains both LP mint and freeze authority.
Validator proof covers custom destinations, outbound and unsolicited inbound
transfers, wallet plus Balance deposits, partial and full exit, split legacy
restoration, overfill rollback, and exact integer conservation.

Finalized devnet closure at slots `477191642-477191698` found 15 historical
VaultStake records: five surviving positions are in frozen canonical custody,
four have no position, and six are explicitly retired pre-cohort fixtures. For
every survivor, canonical custody amount, `VaultStake.lp_tokens`, LP mint
supply, and all token-account balances match exactly with no unattributed
holder. The six retired positions are Vaults 2-6 and 15. Their test runners
created random rider keys only in memory and never persisted them, so a real
rider-signed restoration is impossible.

Retirement does not add an admin path or mutate chain state. A checked-in
ledger is bound to the exact devnet genesis, program id, account addresses,
full account hashes, amounts, reward liabilities, and generation-1 activation
quarantine. The inventory rejects any drift before applying the
`retired_fixture` classification; the protocol's rider-signature requirement
remains unchanged. The resulting report contains no restore, seal, or
quarantine decision and is rollout-ready. Evidence:
`docs/design/evidence/LP_CUSTODY_DEVNET_INVENTORY_2026-07-17.json` (SHA-256
`74db00d57fec3ee34628a3b8dc52d4dc0321b7bd545dfe268f8b050f0366837b`) and
`docs/design/evidence/LP_CUSTODY_DEVNET_RETIREMENTS_2026-07-18.json`
(manifest SHA-256
`a9ba7cd9114ada7b4a5c6ece4a50e571db0d9a463e5bdd32e93d97cf22ba4b4f`).

Independent review also found an inherited, separate authority defect in the
Balance-funded deposit and withdrawal instructions: canonical destinations
prevent theft, but a caller can force a rider's deposit or exit and charge the
exit fee without scoped rider consent. That policy question is not part of LP
custody arithmetic and remains P1 follow-up `boulderroller-v2-8348`
(`agent-autonomous` after Tim's 2026-07-17 ratification). The first-settlement
gate depends on it.

Ratified outcome (2026-07-17): quiet or gasless cannot mean permissionless.
Balance-funded Deposit CAL, Withdraw CAL, and CAL+USDC Vault creation require a
rider-created, revocable operation session. Login, UI confirmation, Backend
Authority, fee payer authority, and RiderBalance custody are not consent. Each
operation binds the exact rider, action, Vault, base-unit amounts, session
generation, sequential nonce, and expiry. A wallet-signed path remains the
fallback. Fixed-benefit Collect DUNG may remain permissionless because its
destination is enforced for the rider.

Remediation outcome (2026-07-17): ABI `0x44` adds the rider-derived
`BalanceVaultAuthority` session, rider-signed configure/rotate/revoke
instructions, a seven-day maximum session, and domain-separated exact operation
IDs shared by Rust and backend frozen vectors. The program consumes each nonce
once and rejects wrong signer, action, Vault, amount, generation, expiry,
revocation, Balance lifecycle state, and post-reactivation session reuse. The
backend policy, route intents, coordinator, and builders require the
`rider_session` model and reject generic `app_balance` execution. Red-green
backend proof and the full local validator cover tamper, replay, expiry,
revocation/rotation, lifecycle non-resurrection, wallet fallback, partial/full
withdrawal, LP conservation, and canonical USDC Vault creation.

### P2 - LP withdrawal API rejects exact fractional display LP

Follow-up bead: `boulderroller-v2-lpwx`

Evidence:

- `backend/app/routes/vaults.py:223-225` accepts `lp_amount` as a float display
  amount.
- `backend/app/routes/vaults.py:1496-1502` rejects any fractional display LP
  amount before multiplying by the 9-decimal base-unit multiplier.
- `backend/app/routes/vaults.py:1685-1691` repeats the same rule in the prepare
  route.
- On-chain LP math mints and burns base units. Pro-rata minting and withdrawal
  floor division can leave fractional display LP balances by construction.

Why this matters:

A rider can hold `1.234567890` display LP, but the API only lets them withdraw
whole display LP. Dust can become stranded, and a rounded UI balance can produce
"LP amount must be a whole number" or insufficient-LP confusion.

Critique:

LP is a token-like base-unit amount. The route is applying a human display
integer rule before it reaches the exact amount layer.

Required outcome:

Accept base-unit LP strings, exact decimal LP parsing, or a `withdraw_all` path
that reads the exact on-chain `lp_tokens`. Add tests for fractional display LP
and max/full-exit withdrawal.

Implementation contract (`boulderroller-v2-lpwx`): the Vault API accepts
exactly one decimal-string `lp_amount_base_units` or `withdraw_all: true`.
Prepare and submission read the canonical on-chain position, reject overdraw,
and pass the u64 directly to the transaction builder. The Portal's full-position
action uses `withdraw_all` and never converts LP to a JavaScript number.

### P2 - Climb matching has two active signature math systems

Follow-up bead: `boulderroller-v2-9qii`

Evidence:

- `workout-parse/src/climb/signature.rs` uses a v1 signature with Hamming
  distance on a gradient hash plus metric similarity.
- `workout-parse/src/climb/signature_v2.rs` uses DCT coefficients, geometric
  tolerance, and H3 proximity gates.
- `backend/app/services/vault_indexer.py` prefers v2 when both user and vault
  signatures have it, but falls back to v1.
- `backend/app/services/climb_vault.py::match_climb_pattern` still scores
  candidates with v1 signature similarity plus a tile-overlap boost.

Critique:

The v2 design is much more defensible because it preserves metric closeness in
the low-frequency gradient shape and has explicit geographic gates. The v1
hash/Hamming approach is coarse: small bin/hash changes can look far, and
different shapes can collide into deceptively similar hash distance. Keeping
both paths is fine for migration, but live rider/economy matching needs a
single authoritative path and a visible fallback policy.

Sharper confirmed details from the pasted sweep:

- `backend/app/services/climb_vault.py:300-329` still scores active candidate
  matches with v1 signature similarity plus an H3 tile boost.
- `backend/app/repositories/vault.py:506-531` falls back to v1 similarity when
  v2 is missing or cannot parse.
- `backend/app/services/patterns/climb_signature.py:379-396` returns `0.0` for
  all v2 matching exceptions, which can silently darken v2 matching rather than
  surfacing a missing Rust matcher or bad payload.

Required outcome:

Decide whether v2 is canonical now. If yes, route live matching through v2
where evidence exists, make v1 read-only/migration fallback, and add regression
fixtures for same-climb jitter and cross-city false positives.

Resolution (2026-07-15, `boulderroller-v2-9qii`):

- Canonical v2 is now the sole reward-grade authority. Both economic callers
  use `match_reward_grade_v2`; the database-backed call is rerun immediately
  before completion planning.
- As of `boulderroller-v2-rn80`, new rides bind that output and authoritative
  climb-window power evidence through parser V5 and the immutable `5-ftp-v1`
  pipeline vector. V5 preserves V4 reward matching; V1-V4 hashes and
  provenance remain replayable unchanged.
- Reward matching requires oriented start and end proximity within 150 m plus
  the native H3, geometry, and DCT verdict at the shared 0.90 threshold.
- V1 Hamming, OSM attribution, cached IDs, and start-only compatibility helpers
  remain explicitly non-economic. OSM failure cannot block economic matching.
- Historical backfill now rejects v1-only patterns, and live matching removes
  inactive Vaults before ranking so they cannot suppress an active match.
- New and existing Vaults resolve the legacy v1 key across all riders to one
  explicitly eligible creator-owned geographic v2 identity. Every valid row
  under that key must be pairwise compatible; null eligibility cannot authorize
  the source, while
  cross-wallet/cross-city collisions, non-transitive clusters, and incomplete
  eligible evidence fail closed. The verified v2 and endpoints are persisted
  before replay.
- Live and historical candidate scans do not use stale `indexed_vaults.vert_m`
  as a prefilter; native v2 geometry is the vertical authority. Historical
  discovery additionally includes only economically eligible climb evidence,
  verifies the task's v1 key against the indexed Vault, and requires immutable
  ride completion timestamps.
- Independent lifecycle review found that migration 114 forces receipt-less
  backfill rows to `legacy_unverified`/`validated = false`, while activation read
  only validated rows and accepted an empty seed. A matched ride could therefore
  disappear from the permanent board during a nominally successful activation.
  The legacy projection and generation-1 script now fail before any one-way
  activation, and the unreachable writer body has been removed. The already
  ratified V4-B path starts from a clean program; generation-2 manifest execution
  remains unimplemented and would require a separate decision.
- Live devnet inspection on 2026-07-15 found 16 activation accounts: 15 active
  generation-1 Vaults and one inactive generation-0 Vault. All 15 active Vaults
  carry test stake, pending DUNG, or carry state, so none is eligible for silent
  backend-only reclassification as verified.
- Tim ratified quarantining those generation-1 Vaults on 2026-07-15. New reward
  matching, completions, tribute, and deposits require chain-derived active
  generation 2 or later. The devnet admin pending-reward seeder carries the same
  chain gate, so it cannot bypass the quarantine. Settlement of existing pending
  state, Withdraw CAL, and Collect DUNG remain available so the quarantine
  cannot strand balances.
- REST fallback is exhaustively paginated in both the write-time repository and
  startup preview cache. More than one qualifying active Vault is an explicit
  ambiguity and withholds economics instead of selecting a score/ID winner.
- Momentum detections generate v2 signatures and oriented endpoints inside
  Rust from their exact selected bounds; canonical selection no longer drops
  reward evidence merely because momentum wins a corroborated cluster.
- Momentum and persistence use one fixed canonical smoothing window for v2
  signatures even when terrain-specific detector smoothing differs.
- Canonical signature bounds and localized effort endpoints remain distinct:
  the signature carries shape identity and the oriented endpoints only
  corroborate geography. Because both now gate rewards, endpoint-localization
  changes require an evidence-version bump or full Vault reconciliation before
  deployment; detector tuning cannot silently reinterpret stored identities.
- The full-stack devnet smoke now materializes the same v2 signature and both
  oriented endpoints on its indexed Vault instead of constructing a legacy-only
  fixture that cannot exercise reward-grade matching.
- Native matcher absence raises instead of returning `0.0`, and undefined H3
  grid distance for nonzero anchors fails closed. Corrupt query checksums also
  raise before endpoint rejection and even when there are no candidates,
  instead of being misclassified as malformed candidates.
- Exact `(0, 0)` device no-fix coordinates are suppressed by both native
  detector paths and rejected at the Python authority boundary. Other malformed
  ride geography abstains only the affected climb; matcher or database
  unavailability still fails ride processing.
- V2 distance diagnostics now decode decameter wire values into meters without
  changing the frozen signature bytes.
- Rust persistence indices and Python offsets now share one filtered, stably
  sorted sample space. Red-to-green fixtures cover cross-city, reversed,
  late-start, equal-time, missing-elevation, missing-endpoint, and unavailable
  matcher cases.
- Residual production gate `boulderroller-v2-vj1i`: the established v2
  signature fixture passes on macOS but emits a different signature on Linux
  CI. Because v2 is now the sole reward authority, deployment must preserve the
  existing canonical vector across supported targets or perform a separately
  ratified Vault migration; updating the golden to the Linux output is not a
  valid fix.

### P2 - Canon compiler candidate math is not frozen enough for identity

Follow-up bead: `boulderroller-v2-canc`

**Remediated 2026-07-18.** Compiler v0.2.0 makes the previously implicit
choices executable and documented:

- canonical vertical remains net rise (finish minus start), with cumulative
  positive gain explicitly excluded from identity/economic vertical;
- the always-present topographic-isolation flag is informational, so a score
  >=75 with no material flags can reach `high` confidence;
- the authoritative corridor is a PostGIS geography buffer in meters, H3
  corridor and gate cells conservatively cover that width, and republish
  serially deletes stale cells before inserting the replacement set;
- candidate fingerprint v3 includes a fixed, quantized along-track geometry
  sketch plus ordered way refs, while elevation/profile changes remain under a
  separate profile hash; exact v2 lineage preserves prior review and registry
  ownership, profile-hash changes require review, and ambiguous lineage is
  rejected;
- DEM raster registration is explicit, way-chain elevation seams are bounded
  symmetrically, sub-1m duplicate coordinates cannot inflate grade, and the D1
  named-service rule applies in both export and compile paths.

Red-to-green evidence: thirteen focused pre-change cases failed across Rust canon,
GeoTIFF export, and Python publication. The corrected focused suites pass 21
canon tests, 6 exporter tests, and 41 publisher/ClimbLab tests. Tim's 137-label
review fixture remains in the canon suite. Boundary arbitration remains
separate under `boulderroller-v2-4crx.7`.

**D8 remediated 2026-07-18 under `boulderroller-v2-xkdbb`.** Compiler v0.2.1
keeps all v0.2.0 candidates as an exact compatibility floor and adds only
independently qualifying opposite-orientation spans. The original synthetic
single-road and chained-way crest cases failed red with one candidate instead
of two. Final Pennsylvania/Wissahickon compilation preserved all 1,870
baseline fingerprints with no common-candidate geometry, gate, profile, or
math drift and added 181 unique directional candidates (135 single-way, 46
chained). This outcome does not ratify any named boundary under
`boulderroller-v2-4crx.7`.

Evidence:

- `workout-parse/src/canon/mod.rs:546-568` always appends
  `topographic_isolation_not_scored_v0` before calculating confidence.
- `workout-parse/src/canon/mod.rs:1389-1402` ignores that flag for
  `material_flags`, but still requires `flags.is_empty()` for `high`, making
  `high` unreachable while that flag is always present.
- `workout-parse/src/canon/mod.rs:532-543` computes `vert_m` and average grade
  from net endpoint elevation change, while other climb math often uses positive
  elevation gain.
- `workout-parse/src/canon/mod.rs:1560-1595` stores H3 corridor cells only for
  sampled centerline points plus gates, while
  `backend/sql/111_canon_climb_registry.sql:113-130` describes corridor geometry
  and cells as covering the buffered corridor.
- `workout-parse/src/canon/mod.rs:1598-1611` fingerprints ordered OSM way refs
  and endpoint coordinates rounded to 1e-7 degrees.

Why this matters:

This is not yet the live payout board, but it is the next climb identity layer.
If candidate confidence, corridor fast-path coverage, vertical semantics, and
fingerprint stability are not explicit before ratification, the system will
inherit a new duplicate-math problem in the canon layer.

Critique:

The compiler is promising: it records provenance, profile hashes, gates, and
record-continuity policy. The unresolved math should be made explicit before it
graduates from candidate generation to identity authority.

Required outcome:

Define confidence tiers while topographic isolation is unscored, decide whether
canon vertical is net rise or positive gain, make H3 cells match the actual
buffered corridor contract, and freeze fingerprint stability guarantees with
fixtures that survive harmless resampling/noise.

### P2 - Rewardable TSS/CAL has multiple formulas in the repo

Follow-up bead: `boulderroller-v2-hdhh`

Evidence:

- `backend/app/services/ride_effort_policy.py` uses `TSS -> CAL` at 1:1, with
  display units truncated and base units derived from raw TSS.
- Route-only TSS estimates are blocked from rewardable and tributable CAL.
- `backend/app/services/ride_metrics.py` calculates TSS from power, HR, or a
  duration/distance/elevation estimate.
- `backend/app/services/workout_parse_adapter.py` has a compatibility shim that
  estimates NP as `avg_power * 1.05`.
- `workout-parse/src/metrics.rs` has the strongest NP/TSS math: 1Hz power
  resampling, pause splitting, 30-second rolling average, fourth-power NP, and
  TSS from NP/FTP. It also contains future/post-TGE CAL intensity multipliers.

Critique:

The policy layer has the right safety shape: sensor-backed rides can count,
route-only rides go to review. The risk is formula drift. A compatibility shim
or future CAL multiplier should not be able to become rewardable by accident.
If Rust metrics are the intended authority, every rewardable path should prove
it used Rust metrics or an explicitly equivalent implementation.

The self-reported FTP denominator issue above is the rider-controlled version of
the same authority problem: one authoritative TSS formula still needs one
authoritative FTP input policy.

Required outcome:

Fence compatibility estimates out of live economics, document the single
authoritative TSS-to-CAL formula, and add tests proving that route-only and shim
metrics cannot reach rewardable CAL unless deliberately approved.

### P3 - Emission halving reaches zero without an explicit terminal rule

Evidence:

- `apply_halving` halves `current_emission_rate_bps` with integer division.
- Repeated halvings eventually set the emission rate to `0`.

Critique:

This may be intended. If it is intended, write it down and test it. If it is not
intended, define a floor or terminal epoch behavior. This is not urgent compared
with the overflow and conservation findings, but the emission schedule should
not depend on an implicit integer-division endpoint.

### P3 - Mobile local elevation gain is raw-positive delta

Evidence:

- `mobile/src/services/gpsRecording.ts` accumulates elevation gain from raw
  positive altitude deltas.
- Backend/parser climb and elevation code smooths and filters more heavily.
- Mobile GPS validation does have good fast gates for horizontal accuracy,
  implied speed, acceleration, time monotonicity, and altitude bounds.

Critique:

The mobile math is acceptable for local display and recording feedback, but it
should not be treated as economic authority. Raw positive altitude deltas can
overstate climbing on noisy GPS/barometric data. Keep backend/parser metrics as
the reward authority or align the mobile display algorithm with the backend if
riders will compare the two directly.

## Math surfaces inventoried

### Protocol token constants and units

Files:

- `protocol/anchor/programs/boulder_rollers/src/lib.rs`
- `docs/design/V4B_OPEN_QUESTIONS_RESOLUTION.md`

What exists:

- CAL and DUNG use 9-decimal SPL base units in the live protocol.
- DUNG supply caps, allocation buckets, emission rate, halving, harvest fee,
  exit fee, vault creation costs, and CAL-to-DUNG tribute threshold are
  constants or protocol parameters.
- `DungMintState::apply_emission_rate` already uses a `u128` intermediate.
- `can_mint` and `record_mint` use checked additions.

Critique:

The unit model is mostly coherent on-chain. The main on-chain unit bug is not
the constants; it is the remaining direct `u64` settlement share products. The
config validator also sums `u64` bps fields directly, so hostile huge bps input
can abort validation instead of returning false. That is a lower-risk variant
of the same arithmetic-width problem.

### Ride CAL and effort policy

Files:

- `backend/app/services/ride_effort_policy.py`
- `backend/app/services/ride_metrics.py`
- `backend/app/services/workout_parse_adapter.py`
- `workout-parse/src/metrics.rs`
- `backend/tests/services/test_ride_processor_units.py`
- `backend/tests/services/test_ride_processor_client_contract_smoke.py`

What exists:

- `ride_effort_policy` computes display CAL as `int(tss)` and base units as
  `int(tss * 1e9)`.
- It blocks manual-review, pre-economy, future, stale, overlong, and route-only
  rides from rewardable/tributable CAL.
- Python `ride_metrics` can estimate TSS from power, HR, or route shape.
- Rust `workout-parse` has the stronger NP/TSS implementation.

Critique:

The policy gate is strong and should stay. The drift risk is that there are
multiple TSS implementations and one future CAL multiplier implementation in
the repo. The audit did not prove that the compatibility shim is unreachable
from rewardable CAL, so that needs a targeted fence/test.

### Climb completion and CAL tribute

Files:

- `backend/app/services/climb_economy_processor.py`
- `protocol/anchor/programs/boulder_rollers/src/lib.rs`

What exists:

- Backend computes per-climb tribute from ride CAL, climb time share, and a
  grade-based intensity multiplier.
- Chain records completion, personal best, KOM, leaderboard, per-vault tribute,
  and weekly pending rewards.
- Receipts prevent duplicate ride/vault completion writes.

Critique:

This is the weakest conservation surface. There is no aggregate ride-level
budget on-chain, and the backend formula can exceed the ride's earned CAL
across multiple climbs. Either rename/reframe tribute as independent score
credit or make it conserve.

This surface also contains the strongest lifecycle bug found in the addendum:
the DB can mark a completion invalid while the backend still writes the on-chain
Record Board, and late rides can pass CAL age policy while failing the vault
settlement-window policy.

### Settlement distribution and bucket carry

Files:

- `protocol/anchor/programs/boulder_rollers/src/lib.rs`
- `backend/tests/truths/alignment/test_settlement_conservation_gate.py`
- `protocol/anchor/tests/boulder_rollers_protocol_truths.spec.ts`

What exists:

- Base DUNG is split into Record Royalty, stakers, Local Legend, POL, and
  treasury.
- Basis-point floor dust is assigned to Record Royalty before bucket-local carry.
- Empty or partial buckets carry forward.
- Staker unlock percentage grows with eligible staker count.
- Recipient-level DUNG floor dust stays in the bucket carry.

Critique:

The accounting model is good. The implementation width and recipient-set
completeness are not yet good enough. The current tests prove conservation of
the model, not overflow safety or complete recipient discovery.

### Staking, LP, harvest, and exit fees

Files:

- `protocol/anchor/programs/boulder_rollers/src/lib.rs`
- `protocol/anchor/tests/boulder_rollers_protocol_truths.spec.ts`

What exists:

- Deposits mint LP pro rata with checked `u128` math.
- Withdrawals burn LP and return pro-rata CAL.
- Exit fee is `50` bps.
- Harvest fee is `500` bps.
- One-staker happy-path tests exercise deposit, settlement, harvest, withdraw,
  and fees.

Critique:

The core formulas are conventional. The missing piece is invariant coverage
outside the 1:1 happy path, a clear definition of `stake.cal_staked`, and exact
LP amount handling in backend withdraw routes.

### Climb detection, signatures, and terrain scoring

Files:

- `backend/app/services/patterns/climb.py`
- `backend/app/services/patterns/climb_signature.py`
- `backend/app/services/climb_vault.py`
- `backend/app/services/vault_indexer.py`
- `workout-parse/src/climb/signature.rs`
- `workout-parse/src/climb/signature_v2.rs`
- `backend/app/services/terrain_bootstrap.py`

What exists:

- Detection uses elevation smoothing, uphill segmentation, vertical gain,
  distance, grade, VAM, duration windows, sparse/GPS quality guards, and
  heuristics for trimming/selection.
- v1 signatures use gradient hash/Hamming distance plus metrics.
- v2 signatures use DCT shape distance, geometry tolerance, and H3 proximity.
- Terrain bootstrap has a GPD/POT significance model with threshold stability
  diagnostics.

Critique:

The detector math is rich but split. v2 signature matching is clearly more
audit-friendly than v1 hash matching. Terrain significance looks like a useful
research/admin scorer, but it should not drive rider-visible or economic
decisions until calibrated against accepted ride/climb fixtures and documented
as the canonical scoring layer.

The canon compiler is the next version of this same authority question. Treat
its confidence, corridor-cell, vertical, and fingerprint math as identity
semantics before ratifying candidate climbs.

### Mobile GPS recording math

Files:

- `mobile/src/services/gpsRecording.ts`
- `mobile/src/lib/gpsValidation.ts`
- `workout-parse/src/climb/utils.rs`

What exists:

- Sample offsets subtract GPS sample timestamp, ride start wallclock, and
  paused duration in one explicit clock-domain calculation.
- Distance uses haversine and caps per-step distance at 500m.
- Moving time is capped at 5 seconds per accepted sample gap.
- Validation rejects null-island points, out-of-range coordinates, low
  accuracy, impossible speed, impossible implied coordinate speed, impossible
  acceleration, altitude outliers, and non-increasing timestamps.

Critique:

The validation gates are good. Local elevation gain is the main loose estimate.
Keep it display-only unless it is aligned with backend/parser smoothing.

### Portal and backend amount formatting/action math

Files:

- `backend/app/routes/portfolio.py`
- `backend/app/solana_direct.py`
- `backend/app/services/balance_lifecycle.py`
- `web/portal/src/pages/Portfolio.tsx`
- `mobile/src/lib/chain.ts`

What exists:

- The portal parses decimal user inputs into base units with `BigInt`.
- It then returns `Number(raw)` and rejects values above JS safe integer.
- Backend portfolio lifecycle currently treats human float token balances as
  base-unit balances.
- Mobile chain formatting is comparatively safer because it keeps BigInt-like
  base-unit formatting separated from display.

Critique:

This should be cleaned up before Balance actions are treated as polished
rider-facing flows. Exact token amounts need exact representations end to end.

### Economic ledger exactness

Files:

- `backend/app/services/economic_ledger.py`

What exists:

- Event hashes are computed from deterministic JSON with string-encoded
  numerics.
- Previous event lookup, balance calculation, hash calculation, and insert are
  performed in separate application steps.
- Insert payloads convert exact `Decimal` values to Python floats.

Critique:

This is not a transaction builder, but it is still economic math. A ledger hash
chain should not depend on float round-trips or unlocked read-then-insert
ordering. Move this to an exact, atomic append path before treating the ledger as
auditable truth.

## Post-audit validator finding: settlement resource envelope

The completion-evidence validator gate exposed a composition failure outside
the original formula census. Settlement arithmetic can conserve every bucket
and still be unexecutable when the complete stake inventory, recipient accounts,
compute budget, and legacy transaction encoding are combined.

- The generic `200,000` CU limit is not stable at four random stake PDAs and
  deterministically rejects the ten-account stress shape.
- The initial ten-account shape with nine positive allocations consumed
  `227,274` CU. Adding the complete ten-place Leaderboard and active Local
  Legend raised repeated random-PDA measurements to `303,685`-`317,185` CU.
  The settlement-only request is therefore `450,000`, leaving `132,815` CU of
  headroom at the observed high-water mark, and more than ten inventory
  accounts remain compute-unproven.
- Compute headroom does not solve transaction size. A full ten-place
  Leaderboard, active Local Legend, separate fee payer/backend authority, and
  pre-existing recipient ATAs serialize as a legacy transaction to
  `1,100 + 33N` bytes. Four stake accounts are exactly 1,232 bytes; five are
  1,265 bytes.
- Same-transaction recipient ATA creation can exceed 1,232 bytes with zero
  stakers. `boulderroller-v2-8uv2` landed the ratified repair on 2026-07-18:
  recipient ATAs are prepared separately and idempotently; settlement remains
  one atomic instruction carried by a managed per-Vault v0 address lookup
  table.
- Preparation persists the lookup-table generation, ordered account-manifest
  SHA-256, activation/extension slot, transaction version, and exact signed
  size. Submission reproduces those values from finalized reads and rejects
  any drift before signing. Unsigned drift returns to preparation; a prepared
  or accepted signature remains reconciliation-only.
- The reviewed v0 ceiling is 900 bytes, below Solana's 1,232-byte packet limit.
  The two-signer full Leaderboard plus Local Legend and ten-stake shape
  serialized to 474 bytes; local-validator proof simulated and landed that
  complete transaction at the 450,000-CU settlement limit.

Follow-up beads: `boulderroller-v2-ijq4` for the measured compute envelope and
durable attempt evidence; `boulderroller-v2-8uv2` for the ratified transaction
capacity architecture.

Deployed proof on 2026-07-18 used the same durable preparation path. Vault 16's
recipient ATA, lookup-table generation, extension, and frozen manifest were
finalized before its 437-byte settlement transaction. The exact position then
withdrew and harvested successfully. Six older generated-key devnet fixtures in
Vaults 2-6 and 15 remain deliberately fail-closed pending retirement or
rider-signed restoration; they are not first-cohort positions.

The postflight also caught one P2 read-model gap: the indexer received the
settlement mint notification but missed the later harvest notification while
remaining connected. Finalized reconciliation restored exact SPL supply; bead
`boulderroller-v2-bxehi` bounds that fallback to five minutes instead of the
current daily interval. On-chain issuance, claims, and cap math were unchanged.

## What looks solid

- The ride effort policy's route-only exclusion is the right economic safety
  default.
- CAL display/base separation is explicitly tested in the ride processor unit
  tests.
- Rust NP/TSS math is stronger than the Python compatibility shim because it
  resamples to 1Hz and handles pauses.
- Settlement conservation intent is well specified: bucket-local carry preserves
  DUNG instead of leaking floor dust.
- Supply cap tracking uses checked additions after amounts are known.
- Mobile GPS validation has clear physical gates and same-domain timestamp
  checks.
- v2 climb signature comments explain threshold choices with corpus evidence,
  which is much better than unexplained constants.

## Follow-up beads created

| Bead | Priority | Finding |
| --- | --- | --- |
| `boulderroller-v2-2l9f` | P0 | Use `u128` checked intermediates for DUNG settlement share math. |
| `boulderroller-v2-rbvd` | P1 | Gate on-chain Record Board writes on validated climb times. |
| `boulderroller-v2-rtie` | P1 | Align displayed and paid Record Board tie-breaks. |
| `boulderroller-v2-lrwd` | P1 | Landed 2026-07-14: lifetime tribute flow for accepted delayed rides. |
| `boulderroller-v2-4x3v` | P1 | Project delayed rides from the exact credited settlement flow. |
| `boulderroller-v2-zxoz` | P1 | Conserve per-ride CAL tribute across climb completions. |
| `boulderroller-v2-ftpv` | P1 | Landed 2026-07-14: immutable ride-time reward FTP and economic TSS. |
| `boulderroller-v2-9su7` | P1 | Gate settlement on complete eligible staker enumeration. |
| `boulderroller-v2-d2df` | P1 | Keep token base-unit amounts exact across portfolio boundaries. |
| `boulderroller-v2-ehsh` | P1 | Landed 2026-07-14: exact database-atomic ledger append authority. |
| `boulderroller-v2-a33s` | P1 | Landed 2026-07-14: schema-stable FTP evidence SHA-256. |
| `boulderroller-v2-ijq4` | P1 | Landed 2026-07-15: measured settlement-only CU envelope and durable attempt evidence. |
| `boulderroller-v2-8uv2` | P1 | Landed 2026-07-18: atomic v0 settlement transport beyond the four-staker legacy ceiling. |
| `boulderroller-v2-vj1i` | P1 | Restore cross-platform determinism for authoritative v2 climb signatures. |
| `boulderroller-v2-p4sv` | P1 | Version authoritative climb output and register its immutable parser V4 pipeline provenance. |
| `boulderroller-v2-ypn8a` | P1 | Ratify LP custody authority and prevent VaultStake drift. |
| `boulderroller-v2-8348` | P1 | Landed 2026-07-17: require rider-scoped authority for Balance-funded Vault value actions. |
| `boulderroller-v2-hba4` | P2 | Define LP stake accounting invariants for non-1:1 vault ratios. |
| `boulderroller-v2-lpwx` | P2 | Allow exact base-unit LP withdrawals and withdraw-all. |
| `boulderroller-v2-9qii` | P2 | Make one climb signature matching math path authoritative. |
| `boulderroller-v2-qv7p` | P2 | Remove the divergent PatternEngine tribute preview formula. |
| `boulderroller-v2-canc` | P2 | Landed 2026-07-18: freeze canon confidence, corridor, fingerprint, DEM, and vertical math. |
| `boulderroller-v2-xkdbb` | P2 | Implemented 2026-07-18: preserve the v0.2 candidate floor and append independently qualifying opposite-orientation crest ascents. |
| `boulderroller-v2-hdhh` | P2 | Fence rewardable TSS/CAL to the authoritative metrics path. |

## Recommended execution order

1. Fix `boulderroller-v2-2l9f` first. It is a direct protocol arithmetic bug
   and already contradicts a ratified design decision.
2. Fix `boulderroller-v2-rbvd` and `boulderroller-v2-rtie` before any rider sees
   the Record Board as a paid permanent board.
3. `boulderroller-v2-lrwd` is landed; fix `boulderroller-v2-zxoz` and
   `boulderroller-v2-4x3v` before treating climb tribute/completion and delayed
   finalization projection as conserved ride economics.
4. Fix `boulderroller-v2-9su7` and `boulderroller-v2-ijq4` before broad
   multi-staker settlement. Do not exceed the four-staker full-board legacy
   transaction bound until `boulderroller-v2-8uv2` lands.
5. `boulderroller-v2-ftpv`, `boulderroller-v2-hdhh`, and the FTP deployment fix
   `boulderroller-v2-a33s` landed 2026-07-14. Rewardable TSS/CAL now has one
   versioned metrics engine, an immutable FTP denominator, and a migration that
   is compatible with the active PostgreSQL schema.
6. `boulderroller-v2-ehsh` landed 2026-07-14. Fix `boulderroller-v2-d2df` and
   `boulderroller-v2-lpwx` before polishing Balance or withdrawal flows.
7. `boulderroller-v2-9qii` makes v2 authoritative, but do not deploy it until
   `boulderroller-v2-vj1i` restores the established signature vector on macOS
   and Linux and `boulderroller-v2-p4sv` lands parser V4 provenance. Handle
   `boulderroller-v2-canc` before canon-first climb identity becomes the live
   Record Board authority.
