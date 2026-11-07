# Devnet Restore Drill

**Status:** Post-main bounded drill passed on 2026-07-06.
**Bead:** `boulderroller-v2-u82.5`  
**Scope:** Prove that a devnet wipe can be recovered from Boulder Roller
off-chain attestations and indexer records before any mainnet permanence claim.

## Current Drill Evidence

Evidence from the 2026-07-06 attempt is recorded under:

```text
history/devnet_restore_drill_2026-07-06/preflight.json
history/devnet_restore_drill_2026-07-06/preflight-funded.json
history/devnet_restore_drill_2026-07-06/scratch_bootstrap.json
history/devnet_restore_drill_2026-07-06/public_api_snapshot.json
history/devnet_restore_drill_2026-07-06/restore_plan.json
history/devnet_restore_drill_2026-07-06/self_diff.json
history/devnet_restore_drill_2026-07-06/supabase_source_coverage.json
history/devnet_restore_drill_2026-07-06/balance_projection_resolution_post_main.json
history/devnet_restore_drill_2026-07-06/final_restore_drill_report_post_main.json
```

Observed facts:

| Check | Result |
|---|---|
| Anchor build | Passed with existing Anchor/Solana warnings. |
| Program artifact | `protocol/anchor/target/deploy/boulder_rollers.so`, `1,188,696` bytes. |
| Scratch deploy rent | `8.27421504` devnet SOL. |
| Initial admin key balance | `7.17188356` devnet SOL; underfunded for deploy. |
| Funded admin key balance | `16.19357588` devnet SOL; deploy preflight passed. |
| Faucet attempts | `5`, `2`, `1`, and later `1` SOL airdrops were refused by devnet faucet rate limits. |
| Scratch deploy | Succeeded over QUIC at `4tHAjEra8shH5khMX8iY1qKMWsxUhDvZx1RAAGTm855d`. |
| Scratch bootstrap | ProgramConfig, mint authorities, treasury token accounts, VaultCounter, and DungMintState initialized. |
| Public indexer snapshot | 33 vaults captured from `https://api.boulderroller.xyz/vaults`. |
| Supabase source coverage | Read-only MCP query verified 33 vaults, 54 completions, 18 leaderboard rows, 21 ride attestations, 12 CAL receipts, 8 climb receipts, 11 rider souls, and stake/allocation tables. |
| Replay plan | 33 vault replay actions generated. |
| Diff engine | Self-diff returned zero material divergence. |
| Balance projection resolution | `rider_balance_accounts` and `rider_balance_tokens` are accepted as rebuilt from the Balance operation ledger. The current dev source has no `balance_operations` table and `cal_daily_balances` has zero rows, so there is no active Balance materialized state to replay in this drill. |
| Final report | `result=pass`; source requirements resolved, live and scratch `admin_credit_cal` probes fail unknown-instruction, scratch lane initialized, and material divergence count is `0`. |

The 2026-07-06 pass is bounded to the current devnet source. The scratch
program deploy/bootstrap was executed on-chain. Source coverage was verified
read-only from Supabase and public-vault snapshot diffing is zero. Before any
environment has material Balance rows, the source coverage gate must include
`balance_operations`; RiderBalance account/token state is rebuilt from that
ledger replay instead of treated as independent truth.

## Source Of Truth

The restore source is the off-chain attested history, not the devnet accounts
themselves. A complete source snapshot must include:

| State family | Source table or source |
|---|---|
| Program lane | deployed program id, ProgramConfig, mint addresses, treasury accounts |
| Vaults | `indexed_vaults` plus vault signature, climb metrics, minter, activation fields |
| Record boards | `vault_leaderboards` top-10 rows per vault |
| Completion summaries | `vault_completions` validated rows and aggregate counts |
| Rider identities | `indexed_rider_souls` |
| Ride attestations | `indexed_ride_attestations` plus ride rows carrying attestation fields |
| CAL receipts | `indexed_cal_mint_receipts` |
| Climb receipts | `indexed_climb_completion_receipts` |
| Stakes | indexed `VaultStake` projection or Balance operation ledger-derived stake rows |
| Pending DUNG | `VaultStake.rewards_earned` projection and settlement receipt records |
| Carry balances | weekly settlement carry fields for record board, stakers, local legend, POL, treasury |
| Balance state | RiderBalance accounts/tokens and `balance_operations` support ledger |

The 2026-07-06 Supabase source coverage check found the following row counts in
`boulder-rollers-dev` (`qzkqjevawthyboymqrle`):

| Table | Rows |
|---|---:|
| `indexed_vaults` | 33 |
| `vault_completions` | 54 |
| `vault_leaderboards` | 18 |
| `indexed_rider_souls` | 11 |
| `indexed_ride_attestations` | 21 |
| `indexed_cal_mint_receipts` | 12 |
| `indexed_climb_completion_receipts` | 8 |
| `indexed_stakes` | 22 |
| `indexed_staker_allocations` | 10 |
| `vault_stakes` | 23 |
| `distribution_receipts` | 0 |
| `cal_daily_balances` | 0 |

The post-main drill resolved the unidentified RiderBalance projections by
accepting `rider_balance_accounts` and `rider_balance_tokens` as rebuilt from
the Balance operation ledger instead of restored from a direct indexed
projection. The acceptance is recorded in
`balance_projection_resolution_post_main.json`: live dev has only
`cal_daily_balances` among Balance-like tables, that table has zero rows, and
there is no active RiderBalance projection to restore in this source state.

The public API is not enough for a full restore. It exposes enough to plan vault
replay, but the 2026-07-06 public snapshot correctly marks these gaps:

```text
cal_mint_receipts
climb_completion_receipts
dung_mint_state
mints
pending_rewards
program_config
record_boards
ride_attestations
rider_balance_accounts
rider_balance_tokens
rider_souls
settlement_carry_balances
vault_counter
vault_stakes
```

## Restore Command Sequence

Build the program:

```bash
cd protocol/anchor
anchor build
```

For a scratch program id, Anchor's `declare_id!` must match the scratch id at
compile time. The 2026-07-06 drill proved that deploying the live-id binary to a
scratch program id succeeds at the loader layer but fails the first instruction
with `DeclaredProgramIdMismatch`. Use a temporary local patch to set both
`programs.devnet.boulder_rollers` / `programs.localnet.boulder_rollers` in
`protocol/anchor/Anchor.toml` and `declare_id!` in
`protocol/anchor/programs/boulder_rollers/src/lib.rs` to the scratch program id,
run `anchor build`, deploy that artifact, then restore the source files before
committing.

Run deploy preflight:

```bash
python3 backend/scripts/devnet_restore_drill.py preflight \
  --program-so protocol/anchor/target/deploy/boulder_rollers.so \
  --admin-keypair ~/.config/solana/boulderroller-admin-upgrade-authority.json \
  --rpc-url https://api.devnet.solana.com \
  --output history/devnet_restore_drill_<date>/preflight.json
```

Only continue when `deploy_funded` is true.

Create a scratch program id:

```bash
solana-keygen new --no-bip39-passphrase \
  --outfile /tmp/br-restore-scratch-program.json --force

solana address -k /tmp/br-restore-scratch-program.json
```

Deploy the scratch program:

```bash
solana program deploy protocol/anchor/target/deploy/boulder_rollers.so \
  --program-id /tmp/br-restore-scratch-program.json \
  --buffer /tmp/br-restore-scratch-buffer.json \
  --keypair ~/.config/solana/boulderroller-admin-upgrade-authority.json \
  --fee-payer ~/.config/solana/boulderroller-admin-upgrade-authority.json \
  --upgrade-authority ~/.config/solana/boulderroller-admin-upgrade-authority.json \
  --url https://api.devnet.solana.com \
  --use-quic
```

Use an explicit buffer keypair so failed uploads can be inspected, resumed, or
closed. On 2026-07-06 RPC writes stalled with `Data writes to account failed:
Custom error: Max retries exceeded`; QUIC deployment succeeded.

Create fresh scratch CAL and DUNG mints controlled by the admin key, then
bootstrap the lane:

```bash
cd protocol/anchor
NODE_OPTIONS='--loader ts-node/esm --no-warnings' npx ts-node scripts/setup-devnet.ts \
  --execute \
  --cluster https://api.devnet.solana.com \
  --program-id <scratch_program_id> \
  --program-keypair /tmp/br-restore-scratch-program.json \
  --cal-mint <scratch_cal_mint> \
  --dung-mint <scratch_dung_mint> \
  --admin-keypair ~/.config/solana/boulderroller-admin-upgrade-authority.json \
  --backend-authority-keypair ~/.config/solana/boulderroller-backend-authority.json
```

Capture the source snapshot and replay plan:

```bash
python3 backend/scripts/devnet_restore_drill.py snapshot \
  --api-url https://api.boulderroller.xyz \
  --output history/devnet_restore_drill_<date>/source_snapshot.json

python3 backend/scripts/devnet_restore_drill.py plan \
  --snapshot history/devnet_restore_drill_<date>/source_snapshot.json \
  --output history/devnet_restore_drill_<date>/restore_plan.json
```

The former `backend/scripts/seed_vaults_onchain.py` replay step is disabled. It
copied mutable database projections into generation-1 permanent state and cannot
serve as authoritative restore evidence. This phase remains blocked until the
fresh V4-B deployment lands its canonical `seed_climbs_onchain.py` and records
that script's frozen input contract here. Do not substitute the retired script,
even for a scratch program.

After replay, capture the restored lane snapshot in the same shape as the source
snapshot and compare:

```bash
python3 backend/scripts/devnet_restore_drill.py diff \
  --source history/devnet_restore_drill_<date>/source_snapshot.json \
  --restored history/devnet_restore_drill_<date>/restored_snapshot.json \
  --output history/devnet_restore_drill_<date>/restore_diff.json
```

Passing condition:

```text
material_divergence_count == 0
```

Build the final evidence report:

```bash
python3 backend/scripts/devnet_restore_drill.py final-report \
  --source-coverage history/devnet_restore_drill_2026-07-06/supabase_source_coverage.json \
  --bootstrap-evidence history/devnet_restore_drill_2026-07-06/scratch_bootstrap_post_main.json \
  --diff history/devnet_restore_drill_2026-07-06/self_diff_post_main.json \
  --live-deploy-evidence history/devnet_restore_drill_2026-07-06/live_deploy_admin_credit_negative_post_main.json \
  --balance-projection-resolution history/devnet_restore_drill_2026-07-06/balance_projection_resolution_post_main.json \
  --output history/devnet_restore_drill_2026-07-06/final_restore_drill_report_post_main.json
```

The command exits non-zero if any restore state family is unresolved, if the
diff is non-zero, or if the live/scratch removed-instruction probes stop
returning unknown-instruction.

## Non-Reconstructable State Policy

If any state family cannot be rebuilt from off-chain records, do not accept the
drill. Fix the dual-write or indexer projection first. Current likely pressure
points are `VaultStake.rewards_earned`, settlement carry buckets, RiderBalance
token balances, and any state changed by admin-only repair instructions without
a durable off-chain audit row.

For the 2026-07-06 post-main drill, all state families are classified in
`final_restore_drill_report_post_main.json`. `rider_balance_accounts` and
`rider_balance_tokens` are the only accepted rebuilds; both are accepted because
the current source has zero active Balance rows and future material Balance
state must replay from `balance_operations`.

## Rider Copy Rule

Until the mainnet gate, rider-facing copy must say devnet records are recorded
and guaranteed restored. Do not claim corporation-proof permanence or strong
on-chain permanence on rider surfaces before the funded restore drill passes and
the mainnet gate is ratified.
