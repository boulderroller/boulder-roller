# Boulder Rollers Solana Indexer

IDL-driven indexer that reads on-chain boulder_rollers program state and writes it to Postgres.

## Quick Start

```bash
# Install dependencies
npm install

# Copy and configure environment
cp .env.example .env
# Edit .env with your DATABASE_URL

# Run in development
npm run dev

# Build and run production
npm run build
npm start
```

## Modes

| Mode | Command | Purpose |
|------|---------|---------|
| `snapshot` | `INDEXER_MODE=snapshot npm start` | Bulk fetch all program accounts |
| `stream` | `INDEXER_MODE=stream npm start` | Real-time WebSocket + periodic replay |
| `replay` | `INDEXER_MODE=replay npm start` | Backfill transaction/event history |

Stream mode is the primary production mode. It runs snapshot on startup, then subscribes to account changes via WebSocket with periodic replay sweeps for gap filling.

### Projection ordering

Account state is read at finalized commitment and written with the exact RPC
context slot that supplied the decoded bytes. Every single-row and batch account
upsert rejects a lower `chain_slot`; any legacy null-slot row accepts its first
numbered update. Equal-slot
observations receive a strictly increasing local `indexed_at` tie-breaker so
async query completion cannot reverse callback order within one indexer process.
Sync-state account, replay, and snapshot cursors are independently nondecreasing.
Gap-triggered, initial, and periodic replay requests share one active sweep so
they cannot race equal-slot transaction signatures.

### DUNG supply authority

`DungMintState.total_minted` and its allocation counters are lifetime issuance
and cap state. `DungMintState.total_burned` is Boulder Roller program-burn
telemetry only. Circulating DUNG comes from the configured SPL mint account's
exact `supply` value, projected to `indexed_supply.spl_mint_supply` with its own
finalized `spl_mint_supply_slot`. Snapshot, stream, and reconciliation observe
both sources. The public API returns circulation as unavailable until that mint
observation exists; it never substitutes `total_minted - total_burned` or zero.
Because finalized mint notifications can drop without disconnecting the stream,
an independent finalized RPC refresh runs every four minutes. Health treats a
missing or more-than-five-minute-old supply observation as lagging. Older slots,
and equal-slot observations with a different amount, cannot overwrite the
projection.

Set `DUNG_MINT_ADDRESS` explicitly outside the committed devnet registry.
Before subscribing or publishing supply, the indexer derives and decodes the
finalized on-chain `ProgramConfig` PDA and requires that its immutable DUNG mint
matches this address. Missing, undecodable, uninitialized, or mismatched config
fails closed. Supply amounts remain decimal base-unit strings and must never
cross a JavaScript `number` boundary.

The TypeScript indexer is the only chain reader allowed to write chain-owned
projection fields. Backend services may update disjoint read metadata, but the
retired Python Vault writer cannot be re-enabled. Confirmed creation uses
`vault_creation_handoffs`; replay waits there until this indexer creates a
numbered Vault projection, then v2/GPS metadata attaches without touching the
slot or chain-owned values. The replay worker reconciles committed pairs before
reading ready jobs so overlapping indexer/API transactions cannot strand work.

## Architecture

```
Solana RPC/WS
    |
    v
IDL Decoder (BorshCoder)
    |
    v
Account Router
    |
    +-- Vault Writer      -> indexed_vaults
    +-- Leaderboard Writer -> indexed_leaderboards
    +-- Stake Writer       -> indexed_stakes, indexed_completions
    +-- Legend Writer       -> indexed_legends, indexed_accounts,
    |                         indexed_beetle_cards, indexed_supply,
    |                         indexed_program_config
    +-- Replay Processor   -> indexed_transactions, indexed_events
    +-- Reconciler         -> reconciliation_log
```

## Health Check

```bash
# Basic health
curl http://localhost:3001/health

# Detailed status with table counts
curl http://localhost:3001/status
```

When the Docker host already uses `3001` for something else, override the host mapping:

```bash
INDEXER_HOST_PORT=3002 docker compose -f docker-compose.indexer.yml up --build
curl http://localhost:3002/health
```

## Docker

```bash
docker compose -f docker-compose.indexer.yml up --build
```

## Account Types Indexed

From the boulder_rollers IDL:

| Account Type | Table | Indexed |
|-------------|-------|---------|
| Vault | indexed_vaults | Yes |
| VaultCounter | indexed_vault_counter | Yes |
| VaultLeaderboard | indexed_leaderboards | Yes |
| VaultStake | indexed_stakes | Yes |
| VaultCompletion | indexed_completions | Yes |
| LocalLegend | indexed_legends | Yes |
| UserState | indexed_accounts | Yes (legacy CAL snapshot + rider stats) |
| BeetleCard | indexed_beetle_cards | Yes |
| DungMintState + configured SPL DUNG mint | indexed_supply | Yes; lifetime issuance/program burns plus independently slotted circulating supply |
| ProgramConfig | indexed_program_config | Yes |
| RiderSoul | indexed_rider_souls | Yes |
| RideAttestation | indexed_ride_attestations | Yes |
| CalMintReceipt | indexed_cal_mint_receipts | Yes |
| ClimbCompletionReceipt V1 | indexed_climb_completion_receipts | Yes; identity-only history, version 1, no exact amount |
| ClimbCompletionReceiptV2 | indexed_climb_completion_receipts | Yes; version 2 with raw 32-byte hash and exact decimal tribute |

Completion-flow replay accepts both event generations. V1 events are projected
with evidence version 1; `ClimbCompletionFlowAssignedV2` must declare version 2
and preserves `u64` tribute as a decimal string. Do not convert token amounts
through JavaScript `number`. Solana RPC context slots arrive as numbers and are
rejected unless they are nonnegative safe integers.

### Replay lag monitoring

Replay, lag monitoring and health share one finalized head sample per 30 seconds,
including concurrent calls and cached failures. Snapshot/reconciliation floors
use that same sample. The replay's own signature page proves the saved cursor
was reached at `minContextSlot`; no separate newest-signature probe runs, at
any supported version. Empty/pruned history, incomplete pages and failed processing do not
attest coverage. Health requests read cached observations without calling RPC.
Legacy replay retains its default-retrying finalized connection; Stage 1 uses
a persistent connection with the same SDK rate-limit retries. Head sharing is
keyed by endpoint, so separate connections do not add head reads.
An old last transaction is activity age, not evidence of unprocessed history.

`/health` now labels lag as `finalized_program_history`. `lag_slots` and
`tx_lag_slots` measure head minus verified coverage, expire after 90 seconds,
and are null when unknown. `account_lag_slots` is null: a WebSocket connection
cannot attest complete account coverage. Original activity slots are retained.
Snapshot, replay freshness and supply health gates still apply. This check does
not audit historical projections or certify account completeness.

A structured `indexer_replay_lag` warning is emitted when coverage is unknown,
the latest signature differs, or measured lag is at least 1,000 slots. No
visitor traffic is needed to run the check. Failed first-page replay requests
must not refresh `last_tx_sync_at`.

### Stage 1 program stream and provider budget

Stage 1 uses the pinned release ABI `c0811f476ca9deaf5942e574588bbd68181d701cdc5bfc1719e6fc27a18cd441`.
In stream mode, legacy's existing 30-second signature poll feeds both consumers.
Each new program transaction is fetched once in steady state and passed directly
to legacy replay; Stage 1 retains a proof-stripped, deletion-fenced witness.
Direct calls, CPI and ALT writable accounts all use this same program history.
The standalone consumer uses its own program poll. There is no per-account
signature polling, and neither public nor signed-in Stage 1 reads call RPC.

Discovery pages and their original head are committed together. No source is
consumed until the interval is complete; transactions are ordered by slot and
block position when a slot has multiple program transactions. Singleton slots
need no block-order RPC and carry no invented absolute position. Verified
positions survive retries. An unfetchable transaction or missing required
position holds the contiguous stream after it. Alerts and persisted exponential backoff govern
retry; a successful retry resumes the durable queue. Legacy completion and
Stage 1 consumption are separate. Stage 1 account failures do not stop legacy
projection. A missing/expired finalized coverage heartbeat cannot be renewed by
an idle consumer, and API availability expires after 90 seconds. Cache reuse and
resumed pagination retain the original head sample timestamp (`fence_at`), never
the later processing completion time.

Account projections between boundaries can lag by one refresh. Only accounts
written by newly consumed transactions are refreshed, in batches of at most 100,
using their returned finalized bank slots. Full discriminator/hill-filtered
captures run at bootstrap, within 90 seconds before Monday 12:00 UTC, and on the
first refresh whose finalized head has crossed it. Capture deadlines remain scheduled during replay holds;
missed or unavailable historical banks still hold settlement. Captures cannot
certify coverage until contiguous replay reaches their actual banks. Cost grows
with program activity rather than the number of tracked accounts between these
boundary captures.

The 90-second replay freshness gate uses the original observation's wall-clock
age and needs **no block-time read**. Head block time is read during the 90 seconds
before Monday 12:00 UTC and while a scheduled capture waits for the head to cross
its boundary. There is one necessary freshness exception: a live
adapter-1 test-pool rate with an expiry still ahead of known chain time needs a
head time to keep the public backing expiry check correct. Reads stop once the
rate is definitely expired; production adapters 2–5 use the covered epoch.
All consumers cache that time by head slot. Between those reads, coverage time
is a conservative lower bound from actual transactions and captured banks at or
below the contiguous slot fence. Initial coverage uses an actual checkpoint or
transaction slot/time pair; an empty inventory waits for its first source.
Wall time never becomes chain evidence.
Before any scheduled capture, the shared head's exact time must reach the needed
side of the boundary. A halted pre-noon head causes no post-boundary capture;
waiting costs at most one cached time read per new sampled slot. Every discovery
and dependency bank is bounded by that head slot, and actual dependency times
must not precede its time. A valid capture completes that phase durably, including
across restart and a later chain halt. Only invalid/incomplete captures retry.
Empty inventory stores the head-authorized scheduling time, never a substitute
for chain coverage. Bootstrap and the pre-boundary opening capture are retained.

The following is a **modeled 30-day budget**, not a provider bill. Assume 10 hills,
one canonical Vault per hill, 20 lots per hill and at most 100 dependency accounts
per hill. The baseline averages 60/7 successful boundary captures per month.
Each costs 86 filtered `getProgramAccounts` calls at 10 credits plus 40 ordinary
calls: **900 credits**, or about **7,714/month**. Three pre-boundary head-time
samples and one post-boundary sample per week add about **17/month**. Bootstrap,
additional head-time samples while finality waits and retries of invalid captures
are extra; each extra full capture adds 900. For example, two invalid captures
per weekly boundary add about 7,714/month (about 391,035–441,035 total with
production adapters). A frozen finalized head reuses its cached time and causes
no repeated valid capture. The model does not assume every first capture succeeds.

| Fixed monthly credits | Production adapters | Continuously live fixture rate |
| --- | ---: | ---: |
| Legacy signature polls, supply and reconciliation |119,190|119,190|
| Shared finalized head reads (all consumers) |86,400|86,400|
| Stage 1 boundary captures |7,714|7,714|
| Stage 1 head-time reads |17|86,400|
| Keeper |170,000–220,000|170,000–220,000|
| Combined modeled baseline |383,321–433,321|469,704–519,704|
| Remaining from 1,000,000-credit plan |566,679–616,679|480,296–530,296|

The **head-read share is 86,400 credits, 8.64% of the plan**, counted once.
Legacy alone at 0x4C is now 205,590 fixed credits, including that head share,
versus 378,390 in the previous model. Its other calls are 86,400 replay pages,
32,400 supply refreshes and about 390 daily reconciliation calls. Stage 1 adds
about 7,731 fixed credits with production adapters; it shares the legacy page and
head. A continuously refreshed adapter-1 fixture consumes up to 86,400 head-time
reads including the boundary samples, rather than adding both allowances.

Activity, retries, subscriptions and other API traffic are additional. Add one
block-order read per slot containing at least two program transactions, one
transaction read per new transaction (shared with legacy), and one account read
per 100 written addresses per refresh. Additional pages, Vaults and dependency
batches increase costs. These assumptions leave headroom; they do not guarantee
the plan under arbitrary activity or persistent capture failures.

Bootstrap and mode handoff are separate one-time costs: genesis/epoch/config
checks, activation discovery, historical pages and backfill. A cold legacy
replay may fetch Stage 1 history before Stage 1 backfills it; retries may also
refetch. Handoff preserves an older legacy cursor's pre-activation backlog while
Stage 1 itself starts at activation. Unconsumed sources survive pruning; after
consumption, only sources still needed by unimported boundary tasks are retained.
