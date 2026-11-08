# Reading this repository

This file is for anyone reading this repository, human or agent. In the
working repository this path holds the agent contract; that file is kept
unchanged at `docs/process/AGENTS.md`.

## What this is

Boulder Roller is a training app and a protocol for riding hills. Climbs are
compiled offline from OpenStreetMap and USGS 3DEP elevation data into a
versioned registry, the canon. A rider's ride is parsed, matched against the
canon and attested on Solana, and the rider earns CAL, the effort token, from
the ride's training stress. CAL can be deposited into a climb's vault. Each
week the vault's DUNG emissions are split between the climb's record holders,
its stakers and the protocol.

Two economic layers share one program. The CAL-vault layer above is the one
riders use today on devnet. Stage 1 adds SOL and liquid-staking backing of
hills, with yield paid to riders; it is in the devnet program for rehearsal
and off for riders.

The chain layer runs on Solana devnet. The portal, API and indexer run in
production against it.

## Status

| Part | State |
|---|---|
| Solana program, `protocol/anchor` | This source is program version 0x4E (78), deployed to devnet on 6 Nov 2026. One upgrade key. Not audited. Not deployed to mainnet. |
| API and ride attester, `backend` | Production; CI deploys it from main. |
| Indexer, `indexer` | Production; streams program accounts into Postgres. |
| Rider portal, `web/portal` | Production at boulderroller.xyz; sign-up is invite-only. |
| Native iOS app, `ios` | Builds and tests in CI; not released on the App Store. |
| Ride parser, `workout-parse` | Rust; used by the backend through PyO3 and by iOS through UniFFI. |
| Stage 1 (hill backing) | In the devnet program since 18 Oct 2026. Production flags `STAGE1_UI_ENABLED` and `STAGE1_ACTIONS_ENABLED` are off. The weekly keeper that runs `harvest_stage1` automatically is not merged. |
| `mobile` | Superseded Expo client, kept as reference. |

This repository does not contain user, ride or retention numbers.

## The ride-to-chain path, in reading order

1. Canon compiler: `workout-parse/src/bin/canon_compile.rs:105`, then
   `compile_canon_candidates` at `workout-parse/src/canon/mod.rs:583`. The
   ratified Philadelphia registry is
   `workout-parse/resources/philly_ratified_boundaries_v1.json`, with its OSM
   ways, 3DEP profiles and finish-gate decisions beside it.
2. Ride parsing: FIT at `workout-parse/src/lib.rs:399`, GPX at `:850`, TCX at
   `:1109`. The versioned canonical ride is built in
   `workout-parse/src/canonicalize.rs:270`.
3. Processing and canon traversal: `RideProcessor` at
   `backend/app/services/ride_processor.py:398`; matching against the canon in
   `backend/app/services/canon_traversal.py`.
4. Attestation: `build_onchain_ride_identity` at
   `backend/app/services/ride_attester.py:343`, sent by `send_record_ride` at
   `backend/app/solana_direct.py:2243`.
5. On chain: `record_ride` at
   `protocol/anchor/programs/boulder_rollers/src/lib.rs:366` (bounds checked at
   `logic.rs:677`), then `credit_cal` at `lib.rs:462`.
6. Indexing: `indexer/src/index.ts:46`, account decoding at
   `indexer/src/decoder.ts:162`. The API serves on-chain state from these
   indexed tables.

## The program

Paths below are relative to `protocol/anchor/programs/boulder_rollers/src/`.

- `lib.rs` holds the 106 instruction entry points; about half belong to
  Stage 1. Account constraints are in `contexts.rs`, pure state transitions in
  `logic.rs`, account state in `model.rs`, and unit tests in `tests.rs`.
- Vault LP accounting: `stake_lp_transition` (`logic.rs:141`) and
  `unstake_accounting_transition` (`logic.rs:279`), using checked `u128`
  arithmetic. The instructions that use them are `stake_cal_in_vault`
  (`lib.rs:1997`), `unstake_cal_from_vault` (`:2476`) and `withdraw_to_wallet`
  (`:2827`).
- Weekly distribution: `distribute_epoch_rewards` at `lib.rs:3176`. DUNG
  supply accounting and caps are checked by `assert_solvent` at `model.rs:646`.
  The stakers' 27% unlocks with the number of distinct stakers
  (`STAKER_UNLOCK_PCTS`, `constants.rs:164`): 1% of it at one staker, all of
  it at ten. Each week's locked remainder goes to the record holders. DUNG
  harvests carry a 5% fee and CAL withdrawals a 0.5% exit fee
  (`constants.rs:83` and `:84`).
- Version contract: `advance_program_version` at `lib.rs:236`. The version
  lives in `protocol/program-version.json` and is checked by
  `protocol/scripts/check_program_version.py`. The backend and indexer accept
  a window of versions, so services deploy before the on-chain version moves.
- Stage 1 instructions include `pledge` (`lib.rs:70`), `bond` (`:80`) and
  `harvest_stage1` (`:138`), implemented in `stage1.rs` (`deposit` at `:889`,
  `harvest` at `:1419`). The program identifiers predate the rider vocabulary,
  which says "deposit". `stage1_providers.rs` reads pinned JitoSOL, mSOL and
  JupSOL stake-pool layouts directly, with no CPI. For the SPL pools it
  records the pool's last update epoch so callers can refuse stale rates
  (`stage1_providers.rs:202`). Stage 1 cash and DUNG claims use Merkle proofs.
- Build features in `Cargo.toml`: `stage1-devnet` registers real pool
  identities for devnet rehearsal; `stage1-localnet` simulates rates for local
  tests and pulls in `smoke-helpers`, the test-setup instructions. Neither is
  in the default build.

## Trust model

- Upgrade authority is a single key
  (`G8DM5Dn12fsgkKxbdUUtFVJsqMXTcJqPU9no7koqwcKH` on devnet), and the same key
  is the program config admin. There is no multisig or timelock yet.
  `docs/PROTOCOL_TRUTHS.md` describes a timelocked multisig as a condition for
  later stages, not as current state.
- The backend is trusted to attest rides. `record_ride`, `credit_cal` and
  `distribute_epoch_rewards` require the configured `backend_authority` signer
  (`contexts.rs:111`, `:143` and `:1614`), a separate key held by the API
  server. The program cannot re-derive a ride from the raw file, and the
  backend cannot prove that an uploaded file came from a real ride; it checks
  the file's internal consistency.
- The program's own checks on each attestation (`logic.rs:655` to `:700`) catch
  malformed calls, not a dishonest attester. Timestamps must be at most 10
  minutes in the future and 30 days old, and a ride at most 36 hours long. CAL
  may not exceed one per declared TSS, and TSS may not exceed what an
  intensity factor of 40 sustains, which is 160,000 per elapsed hour. There is
  no per-rider, per-week or total CAL cap, so a compromised attester key could
  credit large amounts to any address.
- Stage 1 rider pay is published as Merkle roots signed by a publisher key set
  on the city account (`set_stage1_publisher`, `lib.rs:3953`;
  `publish_stage1_claim_set`, `lib.rs:3964`). The 65/25/10 split and each
  rider's share are computed off chain, in
  `backend/app/services/stage1_keeper_allocation.py:7`; the program does not
  enforce them, so a compromised publisher key could misallocate a week's pay.
- Climb registration (`register_ratified_climb`, `lib.rs:1298`) requires the
  config admin.
- CAL and DUNG mint authorities are program-derived addresses, listed in
  `protocol/anchor/addresses.devnet.json`.

## Known limits

- Stage 1 yield is small at current sizes. A hill bonds when its backing
  reaches 10 SOL (`S1_LINE`, `stage1.rs:19`); caps are 2,000 SOL per staking
  token, 500 SOL per hill and 5,000 SOL in total (`:20` to `:22`). At
  liquid-staking yields of about 5%, 10 SOL earns about 0.5 SOL a year for the
  whole hill. Outside money can pay riders directly and does not need a bonded
  hill: `sponsor_stage1` and `post_stage1_boost` (`stage1_sponsor.rs`) take
  irrevocable, fee-free USDC for one hill-week, or spread a total across up to
  16 hills for up to 13 weeks. It is paid through the weekly claims on the same
  split as yield: 65% to ascents, 25% to the hill's top ten and 10% to its
  Local Legend (`docs/PROTOCOL_TRUTHS.md:1324`). How much riders should be
  paid, and from which sources, is still being worked out; Stage 1 is off for
  riders in the meantime.
- Settlement pays every staker of a vault in one transaction. The backend
  refuses settlement above ten stakers per vault, because larger shapes are
  unproven (`backend/app/solana_direct.py:4265`,
  `docs/security/MAINNET_GATE.md`). The program does not cap stakers, so an
  eleventh staker would stall that vault's settlement. Scaling past ten needs
  a redesign.
- Four admin instructions seed, replace or activate vault state before a vault
  goes live (`lib.rs:3735` to `:3894`). `docs/security/MAINNET_GATE.md`
  inventories this family for removal before mainnet.
- `constants.rs:141` defines team and investor DUNG caps from an earlier token
  design. No instruction mints into those buckets.
- The parser has ten known defects (among them NaN coordinates, feet read as
  metres, and truncated XML accepted). Each is a test in
  `workout-parse/tests/torture_corpus.rs` marked `#[ignore]`, and fails when
  enabled.
- The portal's CI typecheck covers the files listed in
  `web/portal/tsconfig.gate.json`. A full `tsc --noEmit -p tsconfig.json`
  reports 21 type errors across nine files.
- CI does not run `rustfmt` or `clippy` on the program.
- Solana CI installs the program's JavaScript test dependencies with
  `yarn install --frozen-lockfile`, but `protocol/anchor` has only a
  `package-lock.json`, so those versions are not pinned in CI.

## Check it yourself

Results are from CI on commit `31d6171e0` (5 Nov 2026) unless marked local.
Program integration is from CI on `5963e455b`, the commit this copy was cut from, which moved fixed test ports out of Linux's ephemeral port range. The other commits after `31d6171e0` change only docs, one comment, two unused build scripts and two test ride files.

| What | Command | Result |
|---|---|---|
| Program unit tests | `cd protocol/anchor && cargo test -p boulder_rollers` | 159 passed; about 20 s locally on Apple silicon |
| Same, devnet build | `cargo test -p boulder_rollers --features stage1-devnet` | 159 passed |
| Program integration on a local validator | `python3 protocol/anchor/scripts/run-stage1-ci-group.py --group <name> ...`; exact arguments, groups and toolchain (Agave 2.1.21, Anchor 0.29) in `.github/workflows/solana-ci.yml` | 902 passed across eight groups and three builds. The 30 pending need the test-setup instructions, which only the local build has. |
| Ride parser | `cd workout-parse && cargo test && cargo test --features osm` | 192 passed, then 295 with OSM. PyO3 0.21 needs Python 3.12 or older; set `PYO3_PYTHON` if your default is newer. |
| Backend | `cd backend && pip install -r requirements.txt ../workout-parse && pytest` | 3,962 passed, 145 skipped, about 4 min in CI on Python 3.11. Run `npm ci` in `indexer/` first; one backend test drives the indexer's TypeScript. The tests start their own temporary Postgres, so `initdb` and `pg_ctl` must be on PATH; on macOS also set `LC_ALL=en_US.UTF-8`, and run one suite at a time. Take the placeholder environment from `.github/workflows/backend-ci.yml`. On macOS one Linux-only process test skips, giving 3,961 and 146. |
| Indexer | `cd indexer && npm ci && npm test` | 299 passed |
| Portal | `cd web/portal && npm ci && npm run perf:release` | Unit tests, build, typecheck of the gated file set and 15 static gates |
| iOS | Steps in `.github/workflows/ios-ci.yml` (Xcode 26) | 674 tests, 1 skipped |

The program, parser, backend, indexer and portal commands above were also run
on this copy itself, on macOS, before it was published, with the results
shown. This copy starts from one commit without the working repository's
history, so that history and its CI runs cannot be checked from here.

## Which document wins

When documents disagree, `docs/PROTOCOL_TRUTHS.md` is canonical. Under it sit
`docs/BACKEND_TRUTHS.md`, `docs/PORTAL_TRUTHS.md` and `docs/MOBILE_TRUTHS.md`
for their lanes, then `docs/FRESHEST_SPEC.md` for current product scope and
the frozen inventory. `docs/` holds many older files that describe earlier
designs (a points system, a token launch); `docs/README.md` indexes them, and
they are kept as history, not current.

## Not in this copy

- Most of `history/`: dated study notes, reports and screenshots. The few
  data files and specs that code, tests or CI read are kept in place.
- `archive/`: retired clients and programs.
- The issue tracker (`.beads/`) and agent tool settings (`.claude/`).
- `docs/legal/`, `docs/grants/`, two pitch decks, and screenshots of other
  apps.
- Four superseded early specs (`docs/spec2025.md`,
  `docs/BOULDER_ROLLERS_V1_SPEC.md`, `docs/DUNG_BEETLE_CYCLING_COMPLETE.md`
  and `docs/DUNG_BEETLE_CYCLING_SPEC.html`) and four iOS screenshots of real
  ride routes.
- A personal power profile, `tools/corpus/power_profile.html`.

Links into those paths will not resolve. Apart from this file, a note at the
top of `CLAUDE.md`, `README.md`, which is rewritten for this copy, and
`docs/README.md`, which drops its entries for files not in this copy, every
file is as it stands on main, with these edits:

- One recorded test ride (`docs/in_the_bag_.fit`, and its copies in
  `web/portal/workshop/data/in-the-bag.json` and
  `history/ride-room-2026-09-05/build/capture-fixture.json.gz`) has every GPS
  point within 1 km of its start and end moved to the edge of that circle.
  Timestamps, power, speed, distance and elevation are unchanged, and the two
  hashes that pin the JSON copy are updated.
- A server address in three scripts, one doc and one end-to-end test is
  replaced with a placeholder.
- One email address in an iOS test fixture is replaced.
- The author line of `docs/rfcs/CLIMB_DETECTION_V3_ARCHITECTURE.md` named the
  wrong person and now reads "the founder".

## How it was built

One founder working with AI coding agents under a written engineering
contract: `docs/process/AGENTS.md` and `docs/AGENT_OPERATING_MODEL.md`. The
hooks in `scripts/hooks/` enforce parts of it.
