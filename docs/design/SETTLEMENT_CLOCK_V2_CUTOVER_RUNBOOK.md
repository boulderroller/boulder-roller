# Settlement Clock V2 Cutover Runbook

Status: binding operational procedure for `boulderroller-v2-eanc`
Clock contract: ProgramConfig version 2
Target cadence: Monday 12:00 UTC handoff, Tuesday 12:00 UTC normal finalization

## Purpose

Move the deployed settlement clock from the historical Sunday 11:00 UTC
anchor to Monday 12:00 UTC without changing any stored Settlement Week number.
The program, database, indexer, API, and transaction builders must move as one
maintenance operation. ProgramConfig is the monetary authority; SQL stores an
immutable projection of that exact clock and its source slot.

This procedure does not authorize a mainnet deployment. Mainnet still requires
the existing security and authority gates. It defines the cutover mechanics to
use on localnet, devnet, and, once authorized, mainnet.

## Non-Negotiable Invariants

1. The cutover is a Monday 12:00 UTC timestamp aligned to `1704110400 + K *
   604800` and at least 24 hours in the future when the on-chain migration runs.
2. Timestamps before the cutover retain the legacy `1704020400` conversion.
3. Timestamps at or after the cutover use the v2 `1704110400` conversion.
4. The timestamp immediately before and exactly at the cutover both resolve to
   numeric Settlement Week `K`.
5. Transition week `K` begins at its legacy Sunday 11:00 UTC boundary and ends
   at the following v2 Monday 12:00 UTC boundary. Its duration is 694,800
   seconds. It is the only non-604,800-second week.
6. No authoritative settlement run may exist for week `K` or later before the
   clock contract is bound.
7. Once ProgramConfig records version 2 and the cutover, that pair is immutable.
   Retrying with the same value is allowed; replacing it is not.
8. No service may synthesize a fallback clock while ProgramConfig or its SQL
   projection is unavailable. The API must fail closed.
9. A legacy ProgramConfig migration always requires the worksheet's explicit
   cutover argument. No tool may choose a date automatically.
10. The immutable SQL contract may bind only from a finalized RPC response and
    must retain that response's exact context slot.

## Cutover Worksheet

Record these values in the bead before the maintenance window:

| Field | Required evidence |
|---|---|
| Cluster and program ID | Exact RPC URL and executable program address |
| ProgramConfig PDA | Exact address |
| Pre-migration account size | One known layout: 141, 182, 205, 246, 253, or 325 bytes |
| ProgramConfig source slot | Exact finalized RPC response context slot |
| Chosen cutover `C` | Unix seconds and ISO-8601 Monday 12:00 UTC |
| Cutover week `K` | `(C - 1704110400) / 604800` |
| Transition start | `1704020400 + K * 604800` |
| Transition end | `1704110400 + (K + 1) * 604800` |
| Transition finalizable time | Transition end plus 86,400 seconds |
| Latest authoritative run | Must be less than `K` |
| Last materialized cursor | Must not regress after restart |
| CAL and DUNG mints | Exact configured addresses |
| Release commits | Program, backend, indexer, portal/mobile clients |

Reject the worksheet if the cutover is not aligned, is less than 24 hours in
the future, would renumber the boundary, or conflicts with a run at or after
`K`.

## Maintenance Sequence

### 1. Freeze Writers

Pause all settlement cranks, settlement workers, ride-economy processing,
ProgramConfig indexing, and transaction submission for stake, unstake,
metadata update, and DUNG mint-state initialization. Keep read-only surfaces
available only if they clearly report maintenance or projection unavailability.

Do not let an old client submit against the upgraded instruction account lists.
Do not let the indexer project a partially migrated ProgramConfig.

### 2. Capture Pre-Cutover Evidence

At finalized commitment:

- save the raw ProgramConfig bytes, account length, owner, lamports, and slot;
- decode and record every existing field, especially authorities, mints, POL,
  treasury, and settlement counters;
- record `MAX(settlement_week)` for authoritative runs and the planning cursor;
- count historical completion, distribution, Local Legend, run, job,
  reconciliation, and outbox rows;
- record the latest finalizable week under the legacy clock.

The migration must be rejected if the account length is unknown. Never infer a
layout from `length >= N`; known layouts have exact lengths and offsets.

### 3. Apply the SQL Migration

Apply `backend/supabase/migrations/20260714_126_settlement_clock_v2.sql` through
the normal reviewed database migration path while writers remain paused.

Expected state before ProgramConfig is reindexed:

- historical rows have version 1 provenance and unchanged week numbers;
- settlement runs have frozen v1 start, end, and finalizable timestamps;
- `settlement_clock_contract` exists but has no row;
- `/epoch/current` fails closed instead of inventing a boundary.

Abort if any historical count or stored Settlement Week changes.

### 4. Upgrade the Program

Build from the recorded release commit and complete the cluster's normal
upgrade-authority procedure. Keep all writers paused. The newly upgraded
program intentionally accepts the old ProgramConfig layout only through the
unchecked `migrate_program_config` instruction.

Do not exercise stake, unstake, metadata, initialization, or settlement before
the account migration succeeds.

### 5. Bind ProgramConfig

Submit `migrate_program_config(C)` with the exact worksheet cutover. On devnet,
the repository helper accepts the explicit value:

```bash
SOLANA_CLUSTER=<rpc-url> \
BOULDER_ROLLERS_PROGRAM_ID=<program-id> \
npx ts-node scripts/configure_program_mints.ts \
  --cal-mint <cal-mint> \
  --dung-mint <dung-mint> \
  --settlement-clock-cutover <C>
```

Run that command from `protocol/anchor`. For a multisig-controlled cluster,
construct and approve the same instruction through the authority workflow; do
not substitute a local deployer key.

Immediately verify at finalized commitment:

- ProgramConfig is exactly 334 bytes;
- bytes 325 through 332 decode to `C` as signed little-endian i64;
- byte 333 is version 2;
- all pre-existing bytes decode to the exact pre-cutover values;
- a retry with `C` succeeds idempotently;
- a retry with any other timestamp fails.

If the transaction fails, remain frozen. Never continue with a warning.

### 6. Project the Contract

Deploy/start the matching indexer and wait for a finalized ProgramConfig
projection. Its SQL trigger must create exactly one `settlement_clock_contract`
row with:

- version 2;
- both canonical anchors;
- cutover `C` and week `K`;
- ProgramConfig PDA and finalized source slot;
- source commitment `finalized`;
- a 64-character SHA-256 evidence hash over the clock and source evidence.

The row is immutable. Direct update or delete must fail. A later ProgramConfig
projection may advance the indexed slot but may not replace the contract.
Direct insertion must also fail; only the finalized ProgramConfig projection
trigger may create the singleton.

### 7. Verify Every Consumer

Before resuming writers, prove:

1. `validate_deployment.ts` passes the 334-byte layout, version, alignment,
   mints, and authorities.
2. `GET /epoch/current` returns the exact stored week boundaries and never a
   Unix-zero-derived date.
3. The latest-finalizable calculation is unchanged across restart and does not
   regress from `K - 1` to `K - 2` at cutover.
4. A stake and an unstake simulation include ProgramConfig in the generated
   account list.
5. SQL preserves every completion's original event week and clock-version
   provenance, but does not use that historical week to choose a tribute
   bucket. Accepted tribute enters the Vault's lifetime tribute flow meter at
   the oldest open Settlement Week.
6. A projected distribution finalizes one exact on-chain open flow. Until the
   projection stores evidence of the flow actually credited, it must not infer
   ride `finalized_at` by joining original completion week to distribution
   week; that projection repair is a separately tracked migration.
7. The six `this_epoch` leaderboard functions use the canonical settlement
   week start, independent of database timezone.
8. Portal, backend, and canonical IDL files are byte-identical; mobile generated
   chain types are current; no client owns a settlement anchor.

### 8. Resume in Dependency Order

Resume the indexer first, then API/read services, then transaction builders,
then ride-economy processing, and settlement workers last. Confirm each layer
is healthy before starting the next.

Do not manually clamp or advance the planning cursor. The processor derives the
latest finalizable week from ProgramConfig and the stored run boundaries.

## Boundary Monitoring

For cutover week `K`, capture evidence at all four boundaries:

| Boundary | Expected result |
|---|---|
| `C - 1` | Week `K`, clock version 1 |
| `C` | Week `K`, clock version 2 |
| Transition end minus 1 | Week `K` |
| Transition end | Week `K + 1`, Monday 12:00 UTC |
| Transition finalizable time | Week `K` becomes finalizable |

At the next full week, start-to-end duration must be exactly 604,800 seconds
and finalization must be Tuesday 12:00 UTC.

## Abort and Recovery Rules

- **Before program upgrade:** the SQL migration is backward compatible. Leave
  writers paused, diagnose, and retry without changing `C` unless the on-chain
  migration has never been submitted and the worksheet is formally replaced.
- **After upgrade, before ProgramConfig migration:** remain frozen and complete
  the account migration. No normal instruction is safe against the old size.
- **After ProgramConfig migration:** the clock is bound. Code may be rolled
  back only to a release that reads the same v2 contract. The cutover itself
  cannot be rolled back or replaced.
- **After SQL contract creation:** never edit the contract row. Repair the
  indexer or service consuming it, then replay projections against the same
  ProgramConfig evidence.
- **At any failed invariant:** do not resume settlement or rider economics.
  Preserve transaction signatures, slots, account bytes, SQL snapshots, and
  logs in the bead evidence.

## Completion Evidence

The cutover is complete only when the on-chain account, immutable SQL contract,
API response, settlement processor, generated clients, and runtime PostgreSQL
golden vectors all agree on `C`, `K`, transition boundaries, and provenance.
Passing commands without those observed outcomes is not completion evidence.
