# Boulder Rollers Solana Workspace

Anchor-based programs and tooling for the Boulder Rollers protocol (CAL allocation, vault rewards, single-issuer DUNG).

## Prerequisites

- Rust toolchain (>=1.73) with `cargo`
- Solana CLI 1.16+
- Anchor CLI 0.29.x
- Node.js 18 (see `.tool-versions`)
- Yarn or npm for TypeScript utilities

Install JS deps:

```bash
yarn install
```

## Environment

Copy `.env.solana.example` to `.env` and populate `BOULDER_ROLLERS_PROGRAM_ID`, `CAL_MINT_ADDRESS`, and `DUNG_MINT_ADDRESS` after deployment.
Scripts honour `RPC_URL`, `FEE_PAYER_KEYPAIR`, and program env vars.

For the backend/runtime path, keep these roles separate:

- `SOLANA_PAYER_PATH`: fee payer / rent sponsor
- `SOLANA_BACKEND_AUTHORITY_PATH`: backend authority signer for admin seed and activation flows

Fresh initial-deploy warning: the local deploy keypair must match the target
`BOULDER_ROLLERS_PROGRAM_ID`. An existing upgrade instead uses the established
program address plus its verified upgrade authority; its generated target
keypair is irrelevant and must not redirect the deploy.

## Preflight

Validate local setup:

```bash
./scripts/preflight.sh --rpc https://api.devnet.solana.com
```

Outputs machine-readable JSON with CLI versions and wallet path, then validates:

- address-manifest / runtime / `Anchor.toml` program ID alignment
- initial-deploy keypair pubkey matches the intended program ID, or an existing
  upgrade's live authority matches the dedicated upgrade-authority key
- deployed ProgramConfig / mint authority / vault layout compatibility
- checked-in ABI, append-only snapshots, generated client expectations, and
  `protocol/program-version.json` agree

## Program Version Contract

The checked-in Anchor ABI and every runtime expectation are bound to
`../program-version.json`. V4-B is a fresh-program family bootstrap at `0x4B`;
it does **not** represent an in-place `0x44 -> 0x4B` patch of the V4-A program.
The manifest records V4-A `0x44` as historical predecessor evidence while the
fresh V4-B ProgramConfig initializes both previous and current to `0x4B`.
Subsequent V4-B ABI changes must advance exactly one patch and add an immutable
snapshot.

Validate the repository contract before any build or deployment:

```bash
python3 ../scripts/check_program_version.py --base-ref origin/main
```

Then build and test that exact generated version. A binary built before
`--advance` still contains the prior constant even when the source tree is
current:

```bash
anchor build
python3 scripts/check-deployable-artifact.py target/deploy/boulder_rollers.so
COPYFILE_DISABLE=1 anchor test --skip-build
shasum -a 256 target/deploy/boulder_rollers.so
```

For the fresh V4-B bootstrap, ProgramConfig starts at `0x4B`; there is no
version-advance transaction. For a later adjacent V4-B patch, after deploying
the reviewed binary and completing all required account migrations with writers
paused, advance the finalized ProgramConfig byte with separate admin and payer
keypairs:

```bash
NODE_OPTIONS='--loader ts-node/esm --no-warnings' node \
  scripts/advance_program_version.ts \
  --rpc '<finalized RPC URL>' \
  --program-id '<Boulder Rollers program id>' \
  --admin-keypair '<ProgramConfig admin keypair>' \
  --fee-payer '<powerless fee-payer keypair>'
```

The script accepts only the manifest's exact previous-to-current transition,
waits for finalized confirmation, and proves byte 72 was the only changed
ProgramConfig byte. Keep backend, indexer, and mobile protocol writes paused
until `validate_deployment.ts` confirms the same current version.

## Ratified Climb Registration

Vault identity is admitted through an immutable Climb PDA derived from the
SHA-256 hash of the exact D12 commitment. The registrar consumes a required
post-publish registry-row JSON artifact and recomputes its BLAKE3 canonical
profile hash, D12 bytes, exported commitment evidence, on-chain metrics, and
PDAs. The required wrapper is `boulderroller.canon-registration` schema 1; a
raw pre-publish row is rejected. The tool does not accept raw identity flags.
Dry-run is the default:

The artifact preserves the registry's exact `numeric` length, vertical-gain,
and average-gradient measurements. Its separate `chain_metric_projection`
must name `boulderroller_chain_metric_projection_v1` and carry
`distance_meters`, `vert_decimeters`, and `avg_gradient_basis_points`. The
registrar recomputes each integer using exact decimal half-up projection at
scales 1, 10, and 100, respectively, and rejects missing, extra, mismatched,
negative, non-finite, zero length/vertical, or out-of-range evidence. These
integers populate the existing `u32`, `u32`, and `u16` instruction arguments;
they do not change the program ABI. They also do not enter D12, its SHA-256
hash, the Climb PDA, or the version-index PDA, which remain identity-bound only
to `canon_id`, revision, and canonical-profile hash.

```bash
NODE_OPTIONS='--loader ts-node/esm --no-warnings' node \
  scripts/register_ratified_climb.ts \
  --row '<exported-ratified-row.json>'
```

The report includes the immutable registry-row UUID, commitment evidence,
Climb PDA, version-index PDA, and predecessor PDAs. Successor rows require a
finalized RPC read so the tool can prove the exact current predecessor head.
Only `new_record_board` is operational in this cutover. The on-chain program
and registrar both reject `carry_records_forward` until exact record migration
or shared-Vault continuity is implemented and proved.

V4-B Vault creation is a single reservation-authorized path. The DUNG and
CAL+USDC wallet constructors require the signing `sponsor_authority` to equal
`ProgramConfig.backend_authority` before the global `VaultCounter` can change;
the canonical backend prepare step supplies that partial signature over the
reserved transaction bytes. Direct/admin and Balance-funded constructors stay
closed in V4-B until they can prove the same reservation, so neither an
unreserved wallet transaction nor a backend smoke helper can consume the next
Vault ID.

To submit the verified artifact, use separate ProgramConfig-admin and fee-payer
keypairs. `--send` remains unavailable without every argument below:

```bash
NODE_OPTIONS='--loader ts-node/esm --no-warnings' node \
  scripts/register_ratified_climb.ts \
  --row '<exported-ratified-row.json>' \
  --rpc '<finalized RPC URL>' \
  --program-id '<fresh V4-B program id>' \
  --admin-keypair '<ProgramConfig admin keypair>' \
  --fee-payer '<powerless fee-payer keypair>' \
  --send
```

## Local Development

Start a validator with the bundled config:

```bash
solana-test-validator --reset --config configs/local-validator.json
```

Build and test programs:

```bash
anchor build
anchor test
```

Primary coverage lives in `tests/boulder_rollers_cal_alloc.spec.ts` and staking/vault specs.
Legacy proof/mint tests are archived under `archive/legacy/`.

## Program Layout

`programs/boulder_rollers/src/lib.rs` holds `declare_id!` and the `#[program]`
module, whose instruction order is the IDL order. The rest of the core program
is split by kind and re-exported from the crate root:

| File | Holds |
|---|---|
| `constants.rs` | PDA seeds, protocol limits and economic constants |
| `model.rs` | `#[account]` layouts and the plain types they carry |
| `contexts.rs` | `#[derive(Accounts)]` validation for each instruction |
| `logic.rs` | shared checks and arithmetic called by the handlers |
| `events.rs` | emitted events |
| `errors.rs` | `ErrorCode`, append-only because codes are positions |
| `tests.rs` | unit tests |
| `stage1*.rs` | the stage 1 custody, claims, sponsor and DUNG programs |

Anchor 0.29 sorts IDL accounts and types by module path, so the account module
must sort before `stage1` (hence `model.rs`, not `state.rs`) for the IDL to
stay byte-identical.

## Deployment Workflow

1. Ensure `FEE_PAYER_KEYPAIR` exists (creates on demand):

   ```bash
   ./scripts/keygen.sh --path ~/.config/solana/id.json
   ```

2. Ensure the local deploy keypair matches the intended program ID before any
   deploy or upgrade. For a paused version bootstrap, use the configuration-only
   upgrade preflight because the live version and account layouts are expected
   to be the exact prior state until migration:

   ```bash
   ./scripts/preflight.sh --rpc https://api.devnet.solana.com --upgrade-preflight
   ```

3. Deploy to devnet (build + upgrade) using the reviewed artifact while all
   version-sensitive writers are paused. Complete required account migrations,
   run `advance_program_version.ts`, and validate finalized state before
   resuming matching clients. See
   `../../docs/runbooks/DUNG_RESERVATION_MIGRATION.md` for the current composed
   rollout.

4. Bootstrap / inspect the program lane:

   ```bash
   NODE_OPTIONS='--loader ts-node/esm --no-warnings' npx ts-node scripts/setup-devnet.ts
   NODE_OPTIONS='--loader ts-node/esm --no-warnings' npx ts-node scripts/setup-devnet.ts --execute
   ```

5. Configure program mints and transfer mint authorities:

   ```bash
   npx ts-node scripts/configure_program_mints.ts --cal-mint <CAL_MINT> --dung-mint <DUNG_MINT>
   npx ts-node scripts/transfer_mint_authorities.ts --cal-mint <CAL_MINT> --dung-mint <DUNG_MINT>
   ```

   Sample output:

   ```json
   {"mint":"...","authority_pda":"...","decimals":6,"tx":"..."}
   ```

6. Validate deployment state (ProgramConfig + mint authority + sample vault layout):

   ```bash
   npx ts-node scripts/validate_deployment.ts
   ```

Legacy proof/mint scripts are archived under `archive/legacy/`.

## Artifacts

- IDL: `idl/boulder_rollers.json`
- Devnet addresses template: `addresses.devnet.json`
- TypeScript client: `clients/typescript/index.ts`

The runtime stack mostly reads the JSON IDL, but the Anchor workspace still declares
`clients/typescript` as its generated types output. Keep both checked-in artifacts in sync:

```bash
../scripts/generate_idl.sh
```

That script rebuilds the workspace and copies:

- `target/idl/boulder_rollers.json` -> `idl/boulder_rollers.json`
- `target/types/boulder_rollers.ts` -> `clients/typescript/boulder_rollers.ts`

Commit generated IDLs / address manifests together with protocol changes so backend, indexer,
and any external Anchor consumers see the same interface.

Stage 1 localnet tests use `scripts/build-stage1-localnet.py --test`, a separate
program ID and `.anchor/stage1-localnet` artifacts. Never deploy that binary.
Run the artifact guard from `protocol/anchor` on the exact binary being
deployed; `scripts/preflight.sh` refuses localnet-feature binaries before RPC
or upgrade-authority access. The draft Stage 1 branch must not merge until
Tim signs the devnet upgrade: its 0x4D clients reject the deployed 0x4C ABI.
Read-only exact-mode preflight does not require a local `.so`; it checks any
artifact present. Upgrade preflight always requires and checks the exact binary.
