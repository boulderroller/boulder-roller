# Stage 1 composed devnet upgrade

Owner: `boulderroller-v2-7nijk`. This procedure replaces the separate slice
upgrades, including PRs **#88 and #76**, which are superseded. Stage 1 has one
reviewed `0x4D` ABI and one devnet ELF. All release evidence is local-validator
or offline evidence. This document does not claim a devnet upgrade, deployed
governance, provider yield or real riding. The release task authorizes localnet
only; executing the devnet procedure requires Tim's separate cutover authority.

The candidate uses publisher-funded compact index bitmaps for
cash and DUNG, with multiweek batch claims. The final Solana CI run and artifact
hashes below are release gates; no devnet transaction is authorized by this lane.
The release ABI SHA-256 is `abi_sha256` in `protocol/program-version.json`. At
0x4E it is `c0811f476ca9deaf5942e574588bbd68181d701cdc5bfc1719e6fc27a18cd441`.

0x4E removes legacy instructions and bounds each ride's CAL; it adds no Stage 1
surface. Follow the same order with the version numbers moved up by one. First
ship services that accept 0x4D and 0x4E, with Stage 1 available at both. Then
upgrade. Then advance 77 to 78 with `advanceProgramVersion(0x4D, 0x4E)`.

## 0. Service-first cutover and rollback order

This is the future authorized cutover order; the release task itself does not
merge to main or send devnet transactions.

1. **Merge and auto-deploy first, with the chain still at 0x4C.** The new backend
   and indexer accept exactly 0x4C/0x4D. Legacy account layouts are unchanged;
   Stage1 reads, routes, keeper scopes and projections remain unavailable on
   0x4C. The CI deployment takes about eight minutes. Its deploy job and health
   checks must be green **before Tim signs anything**. Check backend
   `/health/chain` and indexer `/status` report 76 and Stage1 unavailable, and
   ordinary health/legacy paths remain green. Rollback here may restore the
   prior service release while the chain is still 76.
   The deploy script applies additive migration 169 before restarting either
   service. Both use its private genesis/program version record; retain that
   record during service rollback, and stop if either service cannot persist it.
   Migration 169 has a byte-identical Supabase CLI mirror; the keeper's separate
   branch must renumber its colliding 169 when it follows this release.
2. **Tim extends, upgrades and advances the version**, following §§1–4 and the
   reviewed authority flow. Extension alone is irreversible rent/storage but
   changes no program behavior. Before upgrade, abandon the plan and close only
   an unused explicitly owned buffer. After upgrade but before version advance
   or new state, a reviewed compatible prior ELF may be restored. Keep the new
   compatibility services running. After advancing to 77, do not reset the byte
   or restore 0x4C services; pause Stage1 and repair forward.
3. **Confirm both services observe 0x4D.** A finalized config read or service
   restart picks up the advance without redeployment. The network/program
   high-water mark rejects later downgrades; a restart must not hide one. If a
   service fails to observe 77, repair its RPC/config path or restart the new
   service, keeping Stage1 producers off. Do not roll the chain version back.
4. **Bootstrap and run the smoke outcomes in §§5–7.** On failure, disable
   publication and pause intake/settlement as appropriate. Retain funded
   custody, published rights and history. Cash claims and eligible exits remain
   open; mature DUNG claims wait during settlement pause. After new state exists,
   rollback requires a compatible forward repair under the applicable authority
   and delay, not deployment of the old binary.

The exact compatibility window is a service cutover mechanism. Mobile clients
and ordinary operator write paths retain their current-version requirement;
only the constrained version-advance operation accepts 76 as a write precursor.
Missing/invalid config and a version below one already observed are errors,
never invented old values. Unsupported bytes (including 0xFF and 0x4B) are
rejected **before** the durable upsert. In the 0x4D release only 76/77 can
advance the row and 0x4E is unsupported; from the 0x4E release the window is
76/77/78 and 0x4F is the next unsupported byte.
For a row poisoned by an older service, use the exact identity-scoped SQL and
stopped-writer procedure in [service version recovery](STAGE1_SERVICE_VERSION_RECOVERY.md).
Never use that repair to lower a supported 77 or legitimize a chain downgrade.

**Premature supported observation:** an RPC that reports 0x4D before the real
upgrade still passes this exact window and durably pins both services at 77.
Recognize it when backend `/health/chain` or indexer `/status` reports a version
downgrade after the RPC returns 76, while the exact genesis/program observation
row remains 77. Independently verify the finalized ProgramConfig and deployed
ELF through a trusted RPC, and correct the faulty RPC source. Restarting alone
does not clear the pin. Keep Stage1 producers stopped and retain the row; the
unsupported-byte SQL repair cannot lower this supported value. Recovery waits
for the separately authorized real upgrade and advance to 77, then restarts or
refreshes the corrected services against the same database and verifies both
health endpoints and Stage1 availability. Do not delete the row, change its
identity or advance the chain merely to clear the incident.

There are no appended fields in the 25 legacy
account types: the 0x4C/0x4D definitions are byte-identical. New Stage1 types are
unavailable before 77, rather than decoded with fabricated zero defaults.

The Round 4 CI local-validator rehearsal kept one production indexer process
healthy in **98/98 samples** across the real 0x4C ELF, extension, upgrade and
version advance; Stage1 became available only at 77. A fresh-process probe
against the same private PostgreSQL database rejected a downgraded config
fixture. These are local chain and database tests, not deployed-service evidence.

## 1. Preflight — read only, 0 SOL

The [green Round 4 Solana CI run 38708839208](https://github.com/dungbeetlephoenix/boulder-roller/actions/runs/38708839208)
tested source `a77f525610b7620dfdeaecd867267b823f1dc8dd`: all nine jobs passed.
It confirms 480 native tests across three builds, 921 Anchor/service checks,
185 oracle tests and five vector sets, 269 indexer tests, 19 alignment checks,
six Python guards, TypeScript, exact IDL/TS/Expo mirrors and artifact matrix
6/6. The three existing V4-A-only skips remain. All 28 runtime cleanup checks
confirmed zero owned ledgers. Local suites passed the same counts. Legacy
maximum settlement remained 305,284 / 305,302 / 312,802 CU under unchanged gates.
[Backend CI 38708839219](https://github.com/dungbeetlephoenix/boulder-roller/actions/runs/38708839219)
passed 3,156 tests with 21 existing skips; Mobile and Portal CI are green.

The service job passed unchanged on attempt 2 after its first runner could
not bind faucet port 32998 before any tests started. The successful rehearsal
used the exact selected ELF hash, retained one indexer process throughout and
rejected a downgrade after a fresh process read the durable database record.
The final evidence update changes only this runbook and tracker metadata;
the tested release code is unchanged.

The program sources and generated interfaces match keeper commit
`9169d318e2c5b0cc9499d2898fab7bc5e41b37da` byte for byte, retaining unreleased
version 77. Keeper-only harnesses remain on their branch. Earlier release
artifacts are superseded by the registered-total ABI.
The [stage1-release artifact](https://github.com/dungbeetlephoenix/boulder-roller/actions/runs/38708839208/artifacts/11960393267)
contains `.anchor/stage1-devnet/deploy/boulder_rollers.so`; its downloaded
binaries independently passed the 6/6 guard matrix and both IDLs matched source.
Independent builds use Agave 2.1.21, Anchor 0.29.0 and
`scripts/build-stage1-devnet.py`. Run `check-deployable-artifact.py <ELF>
--cluster devnet`; default and marked localnet artifacts remain separate.
The devnet-only pool registration must appear only in the selected devnet IDL.

Record the explicit credential-free RPC origin, genesis hash, program key,
ProgramData key/length/balance, finalized code hash, loader authority,
ProgramConfig admin/version, CAL/DUNG mints, city layout and role keys. Use
`solana genesis-hash`, `solana program show`, and `solana account`, each with
`--url <EXPLICIT_RPC> --commitment finalized --output json` where supported.
Do not infer authority from a local wallet filename. No command here sets the
machine's default cluster or discovers a private key.

The release is `0x4C -> 0x4D` (76 -> 77). Stop on another version. Follow
§0's service-first deployment order; verify the unavailable/available transition
and unchanged legacy behavior. An HTTP response or ABI match does not prove
owner rights or custody.

**This procedure admits fresh Stage1 financial state only.** Historical
predecessor slices expose receipt-based cash claims and older asset, hill,
funding and cursor layouts. Only the city has a historical migration; immutable
recipient registrations are unchanged. A city-only 1c replay is not evidence
that a populated predecessor can upgrade. Stop Stage1 producers during cutover.
Before upgrading, use
`scripts/stage1_cutover.ts --action disable-publisher` with the current admin,
then `--action check-upgrade-inventory` after finalization. Both use the common
explicit-input plan/submit transport below, with input `{}` and admission of
versions 76/77. The disable costs only its transaction fee; the inventory is
read-only. The inventory requires a disabled publisher and scans every known
Stage1 discriminator except city/recipient, without filtering data size. It also
includes the removed receipt/index types and the devnet pool singleton when
using the default IDL. Any result, including undecodable legacy bytes, blocks
this upgrade and requires a compatible migration. Reads advance a monotonic
finalized slot floor, so inventory cannot precede the disabled-publisher witness.
Do not re-enable publication until new code, city migration, and version checks
finish. Repeat the inventory immediately before the loader upgrade; the delayed
upgrade operator also enforces it when proposing and executing. This procedure's
direct disable requires the current signing admin. An already handed-off legacy
installation is admitted only if publication was already finalized-disabled.
With an active publisher it must stop for a separately reviewed legacy-compatible
delayed operation: current `propose-admin` refuses legacy city layouts and does
not cover this case. Do not bypass its authority or delay gates.

At preflight, quote rent from the explicit cluster using finalized
`getMinimumBalanceForRentExemption` and the finalized ProgramData length/balance:

```sh
python3 scripts/stage1-release-costs.py \
  --binary '<REVIEWED_DEVNET_ELF>' \
  --idl idl/boulder_rollers.devnet.json \
  --current-programdata-bytes 1726125 \
  --current-programdata-lamports '<FINALIZED_LAMPORTS>' \
  --rpc '<EXPLICIT_CLUSTER_RPC>'
```

The quote includes 45 ProgramData metadata bytes and 37 buffer metadata bytes.
The offline mainnet reference is `(data bytes + 128) * 6960` lamports; omitting
`--rpc` labels the result as that offline quote, never a devnet quote. The 1,726,125-byte
starting allocation comes from the brief, not a live read in this release.
Recheck it. An already overfunded ProgramData account needs a smaller top-up.
The review reported devnet rent at 5,080 lamports per byte and ProgramData
already holding 10.932 SOL: its then-current binary needed about 3.492 SOL to
extend, 14.425 SOL for the buffer and 17.92 SOL peak. Those are review-time
figures, not this task's live measurement or a quote for the new Round 4 ELF.
Rerun the RPC quote for the exact selected artifact; do not extrapolate the old
peak. Devnet lacked checked extend at that observation. The existing tool reads
the feature account and selects unchecked `ExtendProgram` when it is absent;
it does not guess from a network label.
Transaction fees are additional: query the exact signed message's fee; the
standard base is 0.000005 SOL per signature, without a priority fee. Buffer
uploads span multiple transactions, so their total fee depends on the CLI's
actual message count/retries. Backing deposits are separate from rent/fees.

## 2. Extend before handoff

Use `stage1_governance.ts --action extend-program` with the current admin/loader
authority, the future multisig address and the exact reviewed `binaryLength`.
Its plan binds finalized storage, feature activation and authority, computes
the exact rent top-up and selects `ExtendProgramChecked` when activated; it
never chooses the loader encoding from a cluster label. The code and authority
must remain unchanged after extension. Wait for a later finalized slot.

<!-- RELEASE_STORAGE_QUOTE -->
The selected green CI Round 4 devnet ELF is 2,900,232 bytes (SHA-256
`487281a1b645616e69c05e700b8747f3aa22a303eb20603d8e6813b93a76ea54`).
Its ProgramData target is 2,900,277 bytes, an extension of 1,174,152 bytes from
the brief's starting allocation. The offline mainnet/minimum-balance quote is
8.172097920 SOL extension, 20.186763120 SOL temporary buffer,
28.358861040 SOL peak plus fees. Use the cluster RPC quote
above for devnet; existing overfunding reduces the extension top-up.
<!-- /RELEASE_STORAGE_QUOTE -->

Extension rent stays with ProgramData. Buffer rent is temporary and returns to
the specified spill account after upgrade; do not count it as a permanent cost.
Extension is performed while the explicit current authority still controls the
program. The governance tool refuses extension after vault handoff.

## 3. Upload and upgrade

Verify the exact ELF SHA-256 and every buffer byte before execution. Use a new
explicit buffer key, explicit payer and current upgrade authority:

```sh
solana program write-buffer '<REVIEWED_DEVNET_ELF>' --url '<RPC>' \
  --keypair '<PAYER_KEYPAIR>' --buffer '<NEW_BUFFER_KEYPAIR>' \
  --buffer-authority '<CURRENT_UPGRADE_AUTHORITY_KEYPAIR>'
solana program deploy --url '<RPC>' --program-id '<EXISTING_PROGRAM_KEY>' \
  --buffer '<BUFFER_PUBLIC_KEY>' --upgrade-authority '<CURRENT_UPGRADE_AUTHORITY_KEYPAIR>' \
  --fee-payer '<PAYER_KEYPAIR>'
```

This updates the existing program identity. Verify finalized ProgramData bytes,
SHA-256, retained upgrade authority and the buffer's consumption/refund. Wait
for a later finalized slot before calling new handlers. Retain the previous
ELF and its hash for the rollback decision. If authority is already a Squads
vault, stop using this direct procedure and follow the reviewed delayed
`propose-upgrade/approve/execute` flow in [governance operations](STAGE1_GOVERNANCE.md).

## 4. One version-advance procedure

Use `stage1_release_operator.ts --action advance`. It admits exactly one
`advanceProgramVersion` call, exactly 76 -> 77, canonical ProgramConfig and
current admin, no remaining accounts, and a finalized version-77 assertion.
An already-77 config is a checked no-op. No other release call can use the old
version admission. Cost: no new account rent; the exact transaction fee only.

If authority was already handed to Squads, first perform the permissionless
city migration below when needed, then put this same one 76 -> 77 instruction
into governance `propose-admin/approve/execute` with the vault as admin. Wait
the full seven days and assert finalized version 77. A vault has no direct
admin keypair. CI rehearses the actual pinned 0x4C ELF upgrade and this vault
version advance separately from the historical city migration, on localnet.

```json
{
  "calls": [{
    "name": "advanceProgramVersion",
    "args": {"expectedCurrentVersion": "76", "newVersion": "77"},
    "accounts": {"programConfig": "<CONFIG_PDA>", "admin": "<CURRENT_ADMIN>"}
  }],
  "assertions": [{"account": "<CONFIG_PDA>", "type": "ProgramConfig",
    "fields": {"programVersion": 77}}]
}
```

Run every release operation through the same explicit plan/submit transport:

```sh
node --loader ts-node/esm scripts/stage1_release_operator.ts \
  --mode plan --action '<advance_OR_execute>' --input '<EXACT_INPUT_JSON>' \
  --rpc '<RPC>' --cluster '<localnet_OR_devnet>' --program-interface devnet \
  --program-id '<PROGRAM_KEY>' --admin '<CURRENT_ADMIN>' --fee-payer '<PAYER_KEY>'
# Review saved JSON/digest, then repeat exactly with --mode submit and add:
# --plan '<SAVED_PLAN_JSON>' --digest '<REVIEWED_DIGEST>'
# --fee-payer-keypair '<EXPLICIT_PAYER_FILE>'
# plus only the explicit --admin/--publisher/--operator/--registrar/--guardian-keypair
# required by the instruction's signer metas.
```

`execute` accepts 1–8 explicitly allowlisted IDL calls, exact argument/account
fields and explicit remaining-account privileges. All instruction integers
(including byte-array elements) are decimal strings; unit enum names match
the IDL. Assert nonempty finalized account fields, not just a transaction ID.
For a non-admin signer, include its public key at the input JSON root as
`publisher`, `operator` (person/funder/owner), `registrar` or `guardian`, and
supply that role's explicit keypair option. Account metas alone do not select
a signing key. Guardian vault calls use the dedicated Squads workflow below.
Pubkeys and u64/u128 output assertions use strings; u8/u32 use JSON numbers.
Plans bind the interface/hash and finalized input account bytes. Submit checks
the plan, simulates signed bytes, sends those same bytes and checks finalized
outcomes. A single claim-batch input is split into explicit reviewed transactions
of at most four leaves, each measured against the complete 1,232-byte packet
including signatures and setup. Supply `lookupTables: ["<TABLE_KEY>"]` for
explicit v0 tables where needed; ownership, active state and bytes are checked.
`tokenAccounts: [{"mint":"<PAYOUT_MINT>","owner":"<REGISTERED_RECIPIENT>"}]`
adds idempotent ATA creation paid by the fee payer in the same claim transaction.
Every created transaction appears in the plan. Each chunk is atomic; earlier
successful chunks remain committed if a later chunk fails. Their finalized
signatures print immediately, later chunks stop, and overall success is emitted
only after all outcome assertions pass. Reconcile before planning a retry.
Close calls must assert `type: "account-state", fields: {"exists": false}` for
the closed PDA and `{"exists": true, "lamports": "<EXACT_BALANCE>"}` for the
original rent payer. These balance assertions bind lamports in the reviewed plan. An ambiguous send requires finalized reconciliation,
not a fresh-blockhash retry.

For an existing Stage1 city, call governance `migrate-city` now. The exact
historical layouts 881/897/914/915/931/963 are mapped explicitly into 963 bytes;
unknown layouts fail. Common accounting, existing roles, pauses and explicit
DUNG policy survive. New fields initialize unset. Migration rent is the
finalized minimum-balance delta; from a minimum-funded 881-byte city it is
0.000570720 SOL, from 931 bytes 0.000222720 SOL. A new deployment uses init below.

## 5. Bootstrap assets, roles and disabled DUNG

Use dedicated test keys. Admin, publisher, guardian, registrar, test owner,
fee payer, pool manager/staker and account keypairs remain distinct. The test
pool uses pinned SPL program `DPoo15wWDqpPJJtS2MUZ49aRxqz5ZaaJCJP4z8bLuib`.
Install its pinned CLI separately; fees, validator capacity and backing deposit
amounts must come from the reviewed input, never from this example.

```sh
cargo install --locked --git https://github.com/solana-program/stake-pool \
  --rev 35a63a19d775a9b403551d6e1c31a27b22ad0fc5 spl-stake-pool-cli
spl-stake-pool --version
spl-stake-pool --help

spl-stake-pool --url "$CLUSTER_URL" --program-id "$POOL_PROGRAM_ID" \
  --manager "$POOL_MANAGER_KEY" --staker "$POOL_STAKER_KEY" \
  --token-owner "$TEST_OWNER_KEY" --fee-payer "$PAYER_KEY" \
  create-pool \
  --epoch-fee-numerator '<APPROVED_EPOCH_FEE_NUMERATOR>' \
  --epoch-fee-denominator '<APPROVED_EPOCH_FEE_DENOMINATOR>' \
  --withdrawal-fee-numerator '<APPROVED_WITHDRAWAL_FEE_NUMERATOR>' \
  --withdrawal-fee-denominator '<APPROVED_WITHDRAWAL_FEE_DENOMINATOR>' \
  --deposit-fee-numerator '<APPROVED_DEPOSIT_FEE_NUMERATOR>' \
  --deposit-fee-denominator '<APPROVED_DEPOSIT_FEE_DENOMINATOR>' \
  --referral-fee '<APPROVED_REFERRAL_PERCENT>' --max-validators '<APPROVED_CAPACITY>' \
  --pool-keypair "$POOL_KEY" --validator-list-keypair "$VALIDATOR_LIST_KEY" \
  --mint-keypair "$POOL_MINT_KEY" --reserve-keypair "$POOL_RESERVE_KEY"

spl-stake-pool --url "$CLUSTER_URL" --program-id "$POOL_PROGRAM_ID" \
  --manager "$POOL_MANAGER_KEY" --staker "$POOL_STAKER_KEY" \
  --token-owner "$TEST_OWNER_KEY" --fee-payer "$PAYER_KEY" \
  deposit-sol "$POOL_ADDRESS" '<APPROVED_TEST_DEPOSIT_SOL>' --from "$TEST_OWNER_KEY" \
  --token-receiver "$TEST_OWNER_LST_ACCOUNT"

spl-stake-pool --url "$CLUSTER_URL" --program-id "$POOL_PROGRAM_ID" \
  --manager "$POOL_MANAGER_KEY" --staker "$POOL_STAKER_KEY" \
  --token-owner "$TEST_OWNER_KEY" --fee-payer "$PAYER_KEY" update "$POOL_ADDRESS"

```

The pool must own its nine-decimal legacy SPL mint. Acquire its tokens through
actual deposits, then update the pool; do not mint invented provider inventory.
Review pool, mint, reserve, validator list, supply and current epoch. Branded
mainnet mints unavailable on devnet remain unavailable. Label the registered
asset **SPL test asset**. Register once with `registerStage1TestPool`, refresh
with `refreshStage1Rate`, then enable via `configureAsset(true)`; the pinned
provider/mint remaining accounts must match the IDL and decoder. Existing
`stage1_bootstrap.ts` supplies city/asset/refresh/enable/publisher actions and
asserted idempotent plans. Use the exact caps in its exported `CAPS` object.

Create a distinct six-decimal legacy SPL mint for **test USDC**, an explicit
owner token account, and a reviewed test supply using the installed `spl-token`
CLI's `create-token --decimals 6`, `create-account`, and `mint` commands, with
explicit `--url`, owner, fee payer, mint keypair and destination. Then call
`registerStage1Cash`; devnet refuses canonical mainnet USDC and pins this test
mint once. It never enables principal deposits or charges a harvest fee on
sponsor money. Mint/ATA rent at standard settings: 0.001461600/0.002039280 SOL.

The following calls are supported by `stage1_release_operator.ts --action execute`.
Use exact accounts/arguments from the selected devnet IDL and a finalized
assertion of each named result:

| Call | Required observable result | Permanent rent, excluding fees |
|---|---|---|
| `initCityConfig` | Ratified anchor/caps; roles unset; both pauses false; DUNG ceiling/start both 0 | 963 bytes, 0.007593360 SOL |
| `registerStage1TestPool` | Once-pinned pool/mint, disabled asset, exact provider accounting | 0.006890400 SOL (74 + 367 + 165 bytes) |
| `refreshStage1Rate`, `configureAsset` | Current admitted epoch and intended enablement | No new rent after registration |
| `registerStage1Cash` | Immutable six-decimal test-USDC identity; cash asset disabled for principal | 0.006890400 SOL (74 + 367 + 165 bytes) |
| `configureStage1Dung("0", null)` | **Ceiling and start both unset**; publication refused | 0 SOL rent |
| `setStage1Publisher` | Exact separate publisher | 0 SOL rent |
| `setStage1Registrar` | Exact separate registrar | 0 SOL rent |
| `setStage1Guardian` | Exact separate guardian; existing pause flags preserved | 0 SOL rent |
| `registerRatifiedClimb`, `initHillBond` | Exact canonical identity and admitted hill | Climb + version index + hill: 0.018235200 SOL |

The suggested 20,000 climb-TSS ceiling would allow at most 20 DUNG potential per
hill-week. Bootstrap does not select it or a start week. The shared-mint legacy
burn-counter cutover in STAGE1_SPEC §9 remains a separate gate before enabling
issuance. Already published entitlements survive later policy changes.

## 6. Handoff to seven-day administration

Create the reviewed Squads multisig with `time_lock=604800`, unset configuration
authority, no spending limits and full member permissions. Tim selects members
and threshold; 3-of-5 is the earlier proposal, not an installed fact. The
bootstrap guardian default is a separate small multisig with **no delay**,
revisable by Tim. It pauses/resumes flags only. Registrar authority is restricted
to canonical climb registration and hill admission. Both rotations use the
seven-day admin process and preserve owner rights. Guardian resume is Claude's
default, revisable by Tim: a compromised guardian can lift its own pause, and
replacement still waits seven days. The alternative is a separate pause-only
key; no such change is selected or implemented here.

Create the guardian with the same governance transport **and `--role guardian`**,
`--action create`, explicit `multisig`, `createKey`, `creator`, `members` and
`threshold`. It fixes `timeLock=0`, no configuration authority and no spending
limits. Verify the reported vault, then set that vault as city guardian through
the admin. Actual guardian votes require `--member-keypair`; a vault PDA has no
secret-key file. Direct `--guardian-keypair` pause tests are disposable local
single-key rehearsals only.

For the configured guardian multisig, use `--role guardian` with these actions:
`check` (settings); `propose` with `member`, next decimal `transactionIndex` and
one `call` from `pauseStage1Intake`, `resumeStage1Intake`,
`pauseStage1Settlement`, `resumeStage1Settlement`; `check` again with the same
proposal input; `approve` for each supplied member, adding the returned
`transactionSha256`; then `execute` with that exact hash after the threshold.
The tool reconstructs and compares the stored instruction, keys and privileges,
refuses stale proposals and anything beyond those four calls, and verifies the
finalized flag. There is no clock advance or admin role in this path. Creation
and proposals cost their actual Squads account rent plus fees; votes and flag
execution allocate no BoulderRoller accounts. Guardian rotation still requires
the seven-day admin.

Use governance `create`, inspect its exact plan, then `handoff`; the latter
atomically transfers ProgramConfig admin and loader upgrade authority to vault
index 0. The guardian vault key and registrar key cannot be admin members.
The tool does not compare the human member sets of the two multisigs; Tim
selects those memberships explicitly.
No preapproved transactions may exist. Rent for multisig/config/proposal
accounts is sized by the actual member/instruction input; query it at plan time.
Handoff itself creates no accounts: transaction fees only. Fund the vault only
for explicitly reviewed PDA rent and future proposal execution.

Run governance `check` and verify both authorities, seven-day delay, members,
threshold, role separation, no spending limits, disabled Anchor IDL dispatch,
current city layout, and **every stale Approved proposal**. Any stale Approved
proposal makes status unsafe. Stale Active proposals are permanently
unapprovable and are listed without blocking safety. Before member removal,
reject/cancel affected proposals to terminal state, then repeat the check.
Detailed command/input forms: [governance operations](STAGE1_GOVERNANCE.md).

## 7. Smoke actual outcomes

Use an explicitly labelled synthetic allocation only on the dedicated test
hill, never as rider/field/provider evidence. All Stage1 accounts are created
through program instructions. Retain finalized transaction/account outcomes.

| Sequence | Instruction/tool | Required outcome |
|---|---|---|
| Pledge, then reach the bonding line | `stage1_smoke.ts` pledge/bond or exact release calls | Actual pool-token transfer, correct owner/basis/custody and founder/lock |
| Harvest | `harvestStage1` after actual reserve appreciation and pool refresh | Actual surplus transferred; original principal excluded; funding/fee equality |
| Publish | recipient registration, settlement init/open, snapshot freeze, `prepareStage1ClaimSet`, `publishStage1ClaimSet` | Publisher-funded storage, immutable root, cap, count, recipient binding and accounting |
| Claim | `claimStage1` | Exact recipient transfer, bitmap progress, replay/redirect refusal; zero tracking rent |
| Several weeks | `claimStage1Batch` | One recipient, distinct ordered sets, exact aggregate transfer; bad final proof and frozen-token CPI roll back all entries |
| Sponsor | `sponsorStage1` | Received test USDC admitted once, no yield fee or principal rights |
| Boost | `postStage1Boost`, `processStage1Boost` | Irrevocable funding, minimum 1-USDC hill-week tranche, bounded 1–13 weeks, original-age holds |
| Pause/resume | Guardian intake and settlement calls | Sponsor/boost intake, cash/DUNG publication and mature DUNG claims refuse under their respective pause; resume restores them; cash claims remain open |
| Exit while paused | request/cancel notice, `beginWithdrawal`, `completeWithdrawal` | Same owner, token, principal/loss and lock deadlines; eligible exit remains available |
| DUNG isolated local rehearsal | explicit prospective policy, `publishStage1Dung`, `prepareStage1DungClaimSet`, role roots, `claimStage1Dung`, `claimStage1DungBatch` | Ceiling/cursor/48-hour wait from sealing, separate lifetime accounting, exact mint destination and whole-batch rollback |

Do not enable DUNG on devnet merely to complete a smoke checklist: this cutover
leaves it unset. Local time travel proves boundary behavior without accelerating
real locks. On devnet wait actual deadlines. Existing `stage1_smoke.ts` covers
pledge/bond/harvest/recipient/publish/claim; the exact release operator covers
sponsor, boost, exit, role and DUNG calls. Successful submissions must satisfy
all finalized assertions, including balances and current bitmap/counter state for claims.

Keeper preparation uses the exact final leaf count. Cash sets allocate a
275-byte header plus `ceil(N/8)` bytes; DUNG role sets use 140 bytes plus the
same bitmap. Storage version 2 has no person-key trie. Even 65,536 leaves fit
one allocation. The publisher funds rent and the original preparer receives
any eventual refund; later top-ups donate to that same refund destination.
For DUNG publication, supply `Stage1DungInput.payableRoleTotals` explicitly:
registered rider and backer totals, each no greater than that role's computed
share. Each role root must equal its frozen total; use an empty root for zero.
Missing registrations leave their shares in `Stage1DungMint.unminted`, with
no redistribution or later minting entitlement. Recipient fairness remains
publisher-attested; these bounded totals do not prove the sporting inputs.
Publishers retain the full publication event and each cash claim's 48-byte
`terms` witness with the proof bundle. Publication commits the full audit fields
and extends permanent cursor/hill history. Fully claimed/empty sealed sets may
close; partially claimed sets never expire. Closed namespaces cannot reopen.
The keeper sends cash immediately and DUNG after each role's 48-hour wait;
riders sign only registration and can still submit claims themselves. After
closing cash sets, call `closeStage1WeekFunding` with the canonical absent set,
permanent cursor, asset/earnings and the recorded `rentPayer`. It returns all
funding rent after carrying live ordinary holds into the cursor, including any
prepared release proposal. An untouched skipped book can also close. After
both DUNG role sets close, call `closeStage1DungMint` with its hill, both absent
role PDAs and recorded `rentPayer`; minted counters must equal allocations.
The 226-byte mint record then closes. The hill/cash cursors never close or
rewind, so neither parent nor its sets can be recreated. Lifetime ledgers,
issuance counters and publication commitments survive. Cleanup remains
permissionless during pauses; an unpaid set or required parent cannot close.
The exact release operator supports both close instructions and finalized
`account-state` absence plus original-payer lamport assertions. Cash preparation
requires a frozen snapshot, preventing an unsealed set from being stranded by
an empty-week skip.

The keeper remains off unless `STAGE1_KEEPER_ENABLED=true`; this implementation's
validation sends transactions only to localnet. Before any public enablement,
complete this runbook's existing deployment and historical-boundary gates.
Configure `STAGE1_KEEPER_PUBLISHER_KEYS` as a JSON object containing different
`localnet`, `devnet`, and `mainnet-beta` public keys. The selected secret file must
match the admitted cluster entry. Every signing and resubmission checks a fresh
finalized city account for that publisher. Genesis checking alone is insufficient:
never reuse a publisher key across clusters. The mainnet release flag remains a
separate default-false gate.

Run `python -m app.services.stage1_keeper` as a supervised long-running service,
with its environment and owner-only key file outside the repository. There is no
default step limit. Use the host's service manager with automatic restart on
failure, a 10-second restart delay, and normal SIGTERM shutdown. For systemd, the
unit's service stanza is:

```ini
[Service]
WorkingDirectory=/srv/boulderroller/backend
EnvironmentFile=/etc/boulderroller/stage1-keeper.env
ExecStart=/srv/boulderroller/venv/bin/python -m app.services.stage1_keeper
Restart=on-failure
RestartSec=10
TimeoutStopSec=30
```

On the production droplet the same contract is the compose service `keeper`.
It runs the release's backend image with `restart: on-failure`, a 10-second
delay after any failure and a 30-second stop grace. The release script stops it
before migrations and starts it only after the API and indexer verify. Enable it
in the host `.env`:
- `STAGE1_KEEPER_ENABLED=true`
- `STAGE1_KEEPER_ALLOWED_CLUSTERS=devnet` on the devnet host
- `STAGE1_KEEPER_PUBLISHER_KEYS` holding the three distinct public keys
- `STAGE1_KEEPER_PUBLISHER_KEYPAIR_FILE`: a host file outside the checkout, owned by uid 1000 with mode 400
- `STAGE1_KEEPER_EXPORT_HOST_DIR`: a host directory owned by uid 1000 with mode 700

Fund the publisher before enabling; it pays weekly records and sponsored ATAs.
Inspect without publishing on the release image (manual compose runs need its
tag, which the release script sets):
`APP_VERSION=$(docker inspect --format '{{.Config.Image}}' boulder-repo-api-1 | cut -d: -f2) docker compose run --rm --no-deps -e STAGE1_KEEPER_ENABLED=true keeper python -m app.services.stage1_keeper --costs`.

Keep the same genesis-bound PostgreSQL database and durable proof volume on
restart. After an unclean stop, leases expire within 60 seconds; persisted signed
bytes are reconciled or resubmitted unchanged before another signature is made.
The service queries scheduling once for all scopes and backs idle work off for
up to 900 seconds. It refreshes compatibility and scope discovery every 900
seconds. The existing migration-169 compatibility window is the only cutover
gate: 0x4C reports “not available on this network” and creates no keeper plans;
0x4D starts work without redeployment. Apply keeper migration **170**, with its
byte-identical Supabase mirror and its own five-second lock timeout.

Use `--costs` to inspect finalized fees and outstanding weekly deposits by week.
It includes outstanding lookup-table deposits separately and shows sponsored ATA
rent as recipient-custody outlay. Rare unavoidable tables deactivate after use,
wait for SlotHashes cooldown, and close with a finalized refund witness. Publication and
payout failures that reached the chain still contribute fees. Fully paid sets
and eligible weekly records close automatically. A failed destination produces a
terminal leaf alert; its set stays open while other leaves and weeks continue.
The keeper durably records each destination before erasure can remove claim
preimages. A reclaimed ATA is never sponsored again: that leaf stays open for
self-claim, alerts once, and other assets continue. Low sponsor/publisher SOL
waits with one alert and automatically resumes after funding. Unexpected item
errors stay isolated; failed weekly closes retry with backoff.
Paused settlement produces a deduplicated alert and a 900-second wait. An
accounting mismatch fences its entire mint; restore verified custody/history,
then use `--retry-job` to reconcile the retained plan, never a replacement root.

DUNG freezes registered recipients' payable totals separately from each role's
allocation ceiling. Missing recipients' shares remain unminted in the weekly
record; later registration cannot alter the frozen roots or recover that share.
Before signing or resending, the keeper independently recomputes each role's
registered shares from the frozen measurement and checks the publication input,
roots and signed bytes. A payable-total or saved-plan mismatch refuses publication,
alerts and holds that week; it never refreshes the registration cutoff or repairs
the total silently. Previously published valid obligations remain payable after
inventory reconciliation.
The composed localnet covers an absent registration PDA and pays all registered
recipients. Boost processing still refuses an earned, attributed registration
release after the boost window but before age 26 with `boost_attributed_release_abi`;
its release-interface correction and the historical boundary producer remain
separate enablement gates. The keeper does not extend the ride window.

The module documentation records the same-workload RPC model. At 100 paid people
per hill/week, 10 hills × 2 cash tokens now require about **170k calls/30 days**
(previously 460k) at launch, six months, and twelve months. Adding DUNG for those
hills with 100 riders and 10 distinct backers gives about **220k** (previously
670k); one cash token plus DUNG gives about **175k** (previously 450k). This is
37%, 33% and 39% of the prior estimates. All cycle payouts send before polling,
signatures batch up to 256, and genesis verification plus reconciliation happen
once per cycle. The model includes eight shared payout polling cycles, new SOL
balance/message-fee checks, and the unchanged idle/discovery floor. Provider
credits, retries, boosts, ALT use and unpaid history vary. These are estimates,
not production measurements. Counters are read first; unchanged bitmaps stay cached.

The rider signs registration; the default transaction sponsor pays its
0.001454640 SOL rent and fees. Registration must occur before or in the frozen
snapshot second, so onboarding normally precedes allocation. It is create-once
and unredirectable. For the first payout, that sponsor creates each required
payout ATA idempotently **in the payout transaction**: 0.002039280 SOL per mint
at standard mainnet rent, including each held LST, USDC and DUNG as applicable.
One LST + USDC + DUNG costs 0.006117840 SOL for three ATAs, plus registration =
**0.007572480 SOL** and fees; three LSTs + USDC + DUNG cost **0.011651040 SOL**
including registration. Existing ATAs incur no new rent. This sponsorship occurs
once per recipient/mint; reclaiming the ATA transfers future recreation to its owner. The rider needs no SOL;
the publisher separately pays weekly records and the sponsor pays transaction
fees. Query cluster rent and exact message fees, rather than applying these
mainnet reference figures to devnet.

Actual packet measurement is authoritative. Oversized batches split before any
ALT fallback; realistic individual proofs use plain transactions with zero ALT rent. With one idempotent ATA and one
signature, measured cash batches fit four depth-0 leaves (978 bytes), two
depth-4 leaves (1,168), or one depth-8 leaf (1,071). A depth-12 single with that
setup is 1,263 bytes as legacy and needs an explicit ALT (1,020 bytes in the
fixture). Depth-16 is a single with ALT. Each sibling adds 48 proof bytes;
additional mints, signatures, accounts and witnesses reduce capacity. DUNG has
more fixed accounts and its own measured limits. Four is only the program cap.

### Deposits under automatic payout

Offline standard rent is 6,960 lamports per byte plus 128 bytes overhead.
Assume one cash asset, ten leaves in every set, both DUNG roles, funding opened
at each week's start, finalization after the 24-hour grace, and prompt keeper
payment/cleanup. Additional cash assets add their own funding book/cash set.

| Account | Count/hill-week | Round 4 deposit SOL | Closes |
|---|---:|---:|---|
| Stage1WeekFunding, 499 bytes | 1 | 0.004363920 | After cash set; residual holds carried into cursor |
| Stage1ClaimSet, 277 bytes | 1 | 0.002818800 | After all cash leaves pay at finalization |
| Stage1DungClaimSet, 142 bytes each | 2 | 0.003758400 | After all leaves pay, 48h after role publication |
| Stage1DungMint, 226 bytes | 1 | 0.002463840 | After both role sets close |
| **Total, one cash asset** | **5** | **0.013404960** | **Fully refundable** |

Empty published sets close immediately. Skipped weeks require no records;
any already-opened untouched funding book closes after its skip. Closing a book
with holds moves their original-age/bucket/proposal data into the permanent
cursor and changes no lifetime equality. Pool stays reserved in the asset ledger.

For ten hills, steady weekly deposits cycle from **0.043639200 SOL** (current
funding only) to **0.087278400** during the 24-hour grace (two funding weeks),
then **0.105861600** during the 48-hour DUNG wait. The time-weighted average is
**0.067651200 SOL**. At publication, before paying/closing the prior week, the
transient maximum including the new current-week funding is **0.177688800 SOL**.
These are timing assumptions, not keeper availability evidence. Delayed proof
availability, token-account freezes, settlement pauses or keeper outages can
extend deposits indefinitely; incomplete claims never expire or close.

For ten hills × 52 weekly cohorts, gross deposits and eventual refunds are each
**6.970579200 SOL**: **net recurring rent is 0 SOL**, versus Round 2's
**6.709996800 SOL** under its now-superseded two-unclaimed-leaves assumption.
This excludes transaction fees and the cost of capital. A year-end balance is
refundable outstanding capital, not lost rent. Initial/current-week overlap is
shown above; empty weeks reduce it.

The permanent cursor now reserves 26 carried holds: **6,287 bytes / 0.044648400
SOL per hill/asset**, versus Round 2's 641 bytes / 0.005352240. For ten hills this
is **0.446484000 SOL** of one-time cursor capital (increment **0.392961600**),
separate from the weekly figures. Including these cursors, the modeled steady
range is 0.490123200–0.552345600 SOL, with a 0.624172800 publication transient.
Other permanent/activity accounts below remain additional capital.

Every other Stage1 account has **zero cadence-mandated weekly creation** before
and after. Their one-time or activity-dependent creation is separate:

| Account | Creation trigger (before and after) | Scheduled weekly rent before/after |
|---|---|---:|
| Stage1CityConfig | deployment city | 0 / 0 |
| Stage1AssetConfig | each admitted asset | 0 / 0 |
| Stage1HillBond | each admitted hill | 0 / 0 |
| Stage1SettlementCursor | hill/cash asset | 0 / 0 |
| Stage1Recipient | person registration | 0 / 0 |
| Stage1PledgeLot | each pledge or exit split | 0 / 0 |
| Stage1WithdrawalRequest | each withdrawal request | 0 / 0 |
| Stage1CashConfig | cash singleton | 0 / 0 |
| Stage1Boost | each posted boost, up to 16 hills | 0 / 0 |
| Stage1BoostHill | each boost/hill | 0 / 0 |
| Stage1DungState | issuance singleton | 0 / 0 |
| Stage1TestPool | devnet test singleton only | 0 / 0 |

SPL custody/reserve ATAs and legacy Climb/ClimbVersionIndex are also created on
admission/activity, not weekly. This does not price unbounded new boosts, lots,
withdrawals or riders at zero. Round 2's 32-byte hill/cursor publication commitments remain; the additional
Round 3 cursor capacity and weekly original-payer fields are priced above.
Weekly cadence, per-hill allocation, fees, recipient binding and hold expiry
policy are unchanged. The favorable net figure assumes every payable leaf is
submitted and its records are eventually closed; this release does not deploy
the keeper or establish real-rider payout evidence.

| Leaves/set | Cash rent SOL | Each DUNG role rent SOL |
|---|---:|---:|
| 10 | 0.002818800 | 0.001879200 |
| 100 | 0.002895360 | 0.001955760 |
| 1,000 | 0.003674880 | 0.002735280 |

Claims allocate zero tracking accounts and pay zero per-claim tracking rent.
The old receipt/index pair cost 0.002672640 SOL per claim. Current local cash
batches measured 899 bytes for three shallow weeks; retain the final test
measurements and proof depth with any cost claim. Fixtures and local synthetic
allocations are not rider or devnet outcomes.

## 8. Rollback boundaries

Before upload: abandon the unsubmitted plan at no chain cost. After buffer
upload: close only the exact unused buffer with its explicit authority and
recover rent; retain transaction evidence. After extension: extra storage/rent
remains, while code and authority are unchanged. After upgrade but before byte
advance/new state: pause operations and review a rollback to the retained ELF;
verify its ABI/layout compatibility first. A transaction rollback is not an
application downgrade plan.

After `0x4D` state, immutable roots, withdrawals or handoff exist, never deploy
old code merely because its hash is known. Owner rights, account layouts,
client gates and old entitlements must be preserved. The guardian can pause
new intake/settlement while cash claims and eligible exits remain available;
DUNG claims also wait during settlement pause.
After handoff, upgrade/role changes require the same seven-day process; there
is no guardian emergency-transfer or unilateral-upgrade path. No cleanup,
devnet account closure, version reset, main merge or deployment is authorized
by the local release validation task. Local closure tests use disposable localnet state.
