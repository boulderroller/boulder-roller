# Mainnet Gate

**Status:** agent analysis only. Tim still ratifies the gate criteria and any
mainnet ceremony.
**Bead:** `boulderroller-v2-u82.6`
**Scope in this revision:** completion-evidence V2 cutover, settlement compute
and transaction capacity, rent-cost engineering for settled attestation account
closing, and inventory of the `admin_seed_*`, `admin_override_*`, and
`admin_backfill_*` backdoor family.

## Completion Evidence V2 Cutover

This is a coordinated, pause-and-resume cutover. Do not deploy one writer at a
time while ride economics are live.

1. Pause ride-economic workers and prevent new plan freezes. Let no old backend
   writer race the migration.
2. Apply `125_completion_tribute_evidence_v2.sql`. It adds version/amount
   columns, quarantines every nonterminal V1 plan into review, blocks new V1
   freezes and transitions, and removes V1/mismatched rows from payout-finality
   authority.
3. Deploy the dual-version indexer and readers. V1 accounts remain readable as
   identity-only history; V2 receipts and flow events persist exact version,
   hash, and amount.
4. Upgrade the program and deploy the V2 backend writer/coordinator together.
   `record_climb_completion` must fail closed and all new work must call
   `record_climb_completion_v2`.
5. Deploy API/mobile/BoulderScan consumers, then resume workers only after the
   checks below pass.

Cutover checks:

- V1 instruction returns error 6094 and leaves receipt, budget, Vault, KOM, and
  Record Board state unchanged.
- A V2 hash built with a different tribute returns error 6095 before mutation.
- A valid V2 receipt stores version 2, exact tribute, and the recomputed hash;
  the indexer preserves the same bytes and decimal amount.
- A V1 pending plan is in review and cannot be resumed or reconciled. Reject or
  audit it explicitly; never relabel its receipt as V2.
- A one-unit receipt/flow/DB tribute mismatch leaves `rides.finalized_at` NULL.
- Local-validator and devnet lifecycle smokes both pass against the exact
  deployed program/IDL SHA.

This cutover is roll-forward only once a V2 receipt exists. A rollback build
must retain V2 decoding and writing; falling back to V1 would both lose amount
authority and collide with the same replay-guard PDA.

## Settlement Compute And Capacity

Settlement uses a named `450,000` CU limit; the generic transaction default
remains `200,000`. Local-validator measurements on the current program were:

| Settlement shape | Consumed CU | Result at 200,000 CU |
|---|---:|---|
| Zero settlement-relevant stake accounts | 179,223 | Pass |
| Four settlement-relevant stake accounts | 193,119 to 196,119 on completed random-PDA runs | An additional random-PDA run crossed the limit and failed |
| Ten settlement-relevant accounts, nine positive allocations | 227,274 | Reject |
| Full ten-place Leaderboard, active Local Legend, ten stake accounts | 303,685 to 317,185 across repeated random-PDA runs | Reject |

At the highest observed full production shape, `450,000` leaves `132,815` CU
unused, or 29.5% of the requested limit. Backend preflight rejects more than ten
settlement-relevant `VaultStake` accounts because that larger compute curve is
unproven. The requested limit is durable evidence on the settlement attempt;
`tx_lifecycle.compute_units` mirrors the request while
`indexed_transactions.compute_units` remains actual observed consumption.

Compute is not the only capacity bound. The legacy two-signer shape remains
important red evidence: with ten Leaderboard recipients, one active Local
Legend recipient, both compute-budget instructions, and pre-existing recipient
ATAs, it serializes to `1,100 + 33N` bytes for `N` stake accounts. Four stake
accounts are exactly the 1,232-byte packet ceiling and five are 1,265 bytes.
Creating a missing Local Legend ATA in that same transaction already makes the
zero-staker shape 1,238 bytes.

Production settlement therefore uses one atomic v0 transaction through a
managed per-Vault address lookup table. Preparation performs these operations
before any economic signature exists:

1. Create every missing recipient ATA in its own idempotent, lifecycle-tracked,
   finalized transaction.
2. Plan or reuse one durable lookup-table generation for the Vault and program,
   then extend it in at most 20-address transactions.
3. Require the table to be active, authority-matched, non-deactivated, within
   256 addresses, complete for every non-signer settlement account, and read at
   a finalized slot strictly newer than its last extension slot.
4. Freeze the table address and generation, ordered instruction-account
   manifest SHA-256, last extension slot, and exact signed transaction size.
   The reviewed ceiling is 900 bytes; Solana's hard ceiling remains 1,232.

The complete local-validator shape used distinct fee-payer and backend
authority signers, ten Leaderboard recipients, one active Local Legend
recipient, and ten settlement-relevant stake accounts. It serialized to 474
bytes, simulated, and landed atomically.

Devnet closure evidence on 2026-07-18 used program ABI `0x44` and backend/indexer
release `dc398fbbd541c305374f33a0cdea1bef99efd832`. Migration 137 applied before
the services restarted, and the release passed 27 schema requirements. Vault
16 then prepared its missing recipient ATA and managed lookup table through the
durable service-role RPCs, froze a 437-byte manifest, distributed Settlement
Week 131, withdrew exactly `100000000000000` LP base units, and harvested the
remaining DUNG claim. This proves the devnet gate; it does not replace Tim's
mainnet ratification or the ceremony checks below.

Submission rereads the complete Vault, Leaderboard, Local Legend, recipient,
and `VaultStake` state at finalized commitment and must reproduce that frozen
manifest and signed size. Missing, malformed, deactivated, extended, or
incomplete table state returns an unsigned job to preparation. Once a prepared
or accepted economic signature exists, the job reconciles that signature and
must never reopen or fall back to a legacy transaction.

Deployment evidence must show all of the following against the exact deployed
program and IDL SHA:

- A ten-account validator settlement rejects at `200,000` and succeeds at
  `450,000` with at least `100,000` CU measured headroom.
- An eleven-account inventory is rejected before economic submission.
- A distinct fee payer and backend authority sign a v0 settlement containing
  ten Leaderboard recipients, one active Local Legend recipient, and ten
  settlement-relevant stake accounts; it serializes at or below 900 bytes,
  simulates, and lands atomically.
- Migration `137_settlement_v0_transport.sql` and deploy mirror
  `20260718_145_settlement_v0_transport.sql` are byte-identical. The service
  role can execute the transport functions but cannot read or mutate the
  lookup-generation table directly.
- Recipient ATA creation, lookup-table creation, and every extension have
  finalized lifecycle evidence before the economic attempt is marked ready.
- A stale or incomplete unsigned plan rotates or returns to preparation; a
  signed plan is reconciliation-only. Rollback pauses settlement and rolls
  forward the transport writer rather than resubmitting through legacy.
- The signed settlement contains exactly one CU-limit instruction set to
  `450,000`; the generic submitter still defaults to `200,000`.
- `settlement_attempts.compute_unit_limit` and
  `tx_lifecycle.compute_units` both record `450,000`, and indexed consumed
  CU remains below the configured limit.
- Compute exhaustion and over-inventory errors reconcile once and then block;
  they do not enter an unbounded fee-burning retry loop.
- The actual priority fee agrees with the requested CU limit and the funded
  fee-payer model.

## Rent Model

Measured on 2026-07-06 with `solana rent <bytes> --url
https://api.devnet.solana.com`. Rent-exempt minimums are cluster parameters, so
these are the numbers to refresh at the mainnet ceremony.

| Account | Size | Rent | Mainnet posture |
|---|---:|---:|---|
| Program data, current architecture | ~1.19 MB | ~8.3 SOL | One-time deploy rent. |
| `RideAttestation` | 205 bytes | 0.00231768 SOL | Reclaim after settled finality. |
| `CalMintReceipt` | 81 bytes | 0.00145464 SOL | Reclaim with the settled ride batch. |
| `ClimbCompletionReceipt` V1 | 105 bytes | 0.00162168 SOL | Historical identity-only receipt; no new writes. Reclaim only under the same replay-safe close design. |
| `ClimbCompletionReceiptV2` | 114 bytes | 0.00168432 SOL | Live exact-tribute receipt. Reclaim with the settled ride batch. |
| `VaultCompletion` | 73 bytes | 0.00139896 SOL | Keep; durable rider-vault aggregate. |
| `VaultStake` | 105 bytes | 0.00162168 SOL | Keep while stake is active; close on full exit in a separate unstake cleanup. |
| `Vault` | 593 bytes | 0.00501816 SOL | Keep; durable climb/vault state. |
| `VaultLeaderboard` | 461 bytes | 0.00409944 SOL | Keep; durable record board. |
| `VaultActivation` | 106 bytes | 0.00162864 SOL | Keep; activation/migration evidence. |

Gross per ride with one counted climb:

```text
RideAttestation + CalMintReceipt + ClimbCompletionReceiptV2
= 0.00231768 + 0.00145464 + 0.00168432
= 0.00545664 SOL rent fronted per ride
```

Each additional counted climb on the same ride adds one
`ClimbCompletionReceiptV2`, or `0.00168432 SOL`. The first time a rider ever
counts a given vault also creates or updates the durable `VaultCompletion`
aggregate; do not model that as reclaimable per-ride rent.

At 50 riders:

| Assumption | Gross new rent/month without closing | Steady rent held with 14-day close window |
|---|---:|---:|
| 3 rides/rider/week, one counted climb/ride | ~3.54 SOL | ~1.64 SOL |
| 4 rides/rider/week, one counted climb/ride | ~4.73 SOL | ~2.18 SOL |
| 4 rides/rider/week, 1.25 counted climbs/ride | ~5.09 SOL | ~2.35 SOL |

To hold steady-state rent under 2 SOL/month-equivalent at 50 riders, use a
close window no longer than 14 days at roughly 3 rides/rider/week, or no longer
than about 13 days at 4 rides/rider/week with one counted climb per ride.
Transaction fees still apply, but the rent balance recycles back to the payer.

## Account-Closing Design

Target: close settled per-ride intermediates to the fee payer without losing the
truth a rider sees.

Close candidates:

- `RideAttestation`
- `CalMintReceipt`
- `ClimbCompletionReceipt` V1 and `ClimbCompletionReceiptV2`

Do not close as part of this design:

- `RiderSoul`: lifetime rider aggregate.
- `VaultCompletion`: durable rider-vault aggregate.
- `Vault`, `VaultLeaderboard`, `VaultActivation`: durable climb/vault state.
- `VaultStake`: close only through a full unstake/exit cleanup.

Minimum close preconditions:

- `RideAttestation.finalized == true`.
- `settled_at > 0` and `settled_slot > 0`.
- The CAL receipt and every climb completion receipt for that ride have been
  applied to `RiderSoul`, `VaultCompletion`, record boards, and weekly
  settlement outputs.
- A finality window has passed. Initial engineering target: 14 days; shorten
  only if the 50-rider rent model requires it and Tim ratifies the rider-facing
  old-ride policy.
- Backend source rows keep `ride_hash`, `parser_version`, `source_kind`,
  completion evidence hashes, receipt pubkeys, close tx, close slot, and rent
  recipient.

Recommended instruction shape:

```text
close_settled_ride_intermediates(
  rider,
  ride_hash,
  expected_receipt_count,
  settlement_root_or_evidence_hash
)
```

Accounts:

- mutable `RideAttestation` PDA, closed to `rent_receiver`;
- mutable `CalMintReceipt` PDA, closed to `rent_receiver`;
- zero or more mutable V1/V2 climb-completion receipt PDAs, each closed to
  `rent_receiver`;
- `ProgramConfig`, validating backend authority;
- backend authority signer;
- mutable `rent_receiver`, normally the fee payer that fronted rent.

Replay guard:

Closing idempotency receipts removes the PDA-level "already processed" guard.
Do not ship account closing unless one of these replay guards ships with it:

1. Preferred: a compact `ClosedRideSettlement` PDA keyed by
   `[closed_ride, rider, ride_hash]`, containing only the ride hash, settled
   slot, receipt count, settlement evidence hash, and bump. This spends a small
   tombstone rent balance but still reclaims most per-ride rent.
2. Acceptable with Tim ratification: a weekly settlement output account carrying
   a Merkle root of closed ride hashes plus a policy that old rides at or before
   the closed settlement window cannot be newly attested on-chain.

Without one of those guards, closing receipts makes exact-once enforcement depend
on the off-chain API only, which is not a mainnet-safe design.

## Backdoor Family Inventory

All five matching instructions are currently gated by
`ProgramConfig.backend_authority`, not by the admin authority. On devnet that is
useful for smoke drills and restore work; on mainnet it makes the backend hot
key too powerful unless these paths are removed or moved behind a multisig-only
migration ceremony.

| Instruction | Authority | State it can alter | Built-in guard | Recommendation |
|---|---|---|---|---|
| `admin_seed_vault_completion_summary` | backend authority | `Vault.total_completions`, `kom_holder`, `kom_time_s`; `VaultActivation.seed_completions_written`, `last_seed_at` | Fails after `VaultActivation.is_active` | Remove before mainnet after devnet restore/canon seeding. If a mainnet import is ratified, use a one-shot migration build or require Squads multisig, manifest hash, and post-run removal. |
| `admin_seed_pending_rewards` | backend authority | `Vault.pending_rewards` for the open settlement week | Requires nonzero amount, matching open week, and zero existing pending/carry buckets | Remove before mainnet. This can inject distributable DUNG into a pristine vault and has no normal-production reason to exist. |
| `admin_override_open_settlement_week` | backend authority | `Vault.open_settlement_week`, `last_distribution_epoch` | Requires target week not future and pristine vault economics | Remove before mainnet. Devnet smoke helper only. |
| `admin_override_stake_eligibility` | backend authority | Forces current LP into `VaultStake.effective_lp_tokens` and clears pending snapshot state | Requires positive stake, zero earned rewards, and epoch no later than open week | Remove before mainnet. It bypasses the weekly snapshot activation rule; keep only in devnet smoke code. |
| `admin_backfill_vault_activation` | backend authority | Creates `VaultActivation` and marks it active for a legacy vault | One-shot PDA init; verifies vault owner and PDA seeds | Remove after the clean V4-B/canon deploy path. If Tim ratifies a legacy mainnet migration, run it through Squads multisig with a fixed vault manifest and remove immediately after. |

Adjacent admin helpers not in this requested family:

- `admin_replace_vault_leaderboard` has the same inactive-vault seeding posture
  as `admin_seed_vault_completion_summary`; include it in the same removal or
  multisig migration treatment even though it does not match the requested name
  prefix.
- `admin_activate_vault` is the one-way activation ceremony after seeding; if
  historical seeding remains for mainnet, this should also be multisig/manifest
  bound.

## Ratification Batch

These are intentionally not treated as approved here:

- Final mainnet trigger criteria and go/no-go threshold.
- Exact close window for settled ride intermediates.
- Replay-guard choice for account closing.
- Whether any seeding/backfill helper survives as a multisig-only migration
  path, versus removal before mainnet.
- Timing of permanence copy activation on rider-facing surfaces.
- Ceremony signers and Squads threshold.

Agent recommendation for the batch: remove the devnet smoke helpers before
mainnet; allow only a one-shot, multisig-controlled, manifest-hashed migration
path if Tim explicitly chooses to carry legacy devnet state into mainnet.
