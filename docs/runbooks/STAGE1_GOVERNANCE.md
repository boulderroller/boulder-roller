# Stage 1 governance

Composed release: `boulderroller-v2-7nijk`, incorporating governance
`boulderroller-v2-u6y2s`. Evidence is
local validator execution and offline tests. It does not authorize deployment,
use of the real upgrade key, or a mainnet launch. Continue to apply
[the composed release gates](STAGE1_DEVNET_UPGRADE.md).

## Authority and limits

Squads v4 vault index 0 holds both the loader ProgramData upgrade authority and
`ProgramConfig.admin_authority`. Stage 1 reads that same admin. The proposed
setup is 3 of 5; **Tim chooses the actual signers and threshold**. Every member
has initiate/vote/execute permission. Set `time_lock = 604800`, leave
`config_authority` unset, and create no spending limits. The seven days begin
when the proposal reaches its approval threshold, not when it is created.

Asset admission and enablement, publisher/guardian rotation, ProgramConfig
parameters, fee destinations and signer changes use this vault. The current
city line, asset caps, adapter identities and lock terms have no mutable admin
setter: changing compiled policy requires a delayed program upgrade. The
devnet-only test-pool identity can be registered once through the vault.

The guardian immediately pauses **or resumes** intake and settlement.
Intake blocks pledges, bonds, excluded-pledge conversion, `sponsorStage1` and
`postStage1Boost`. Settlement blocks cash snapshots/roots, hold transitions,
boost processing, cash empty-week skips, DUNG publication, DUNG claim-set
publication, DUNG skips and mature DUNG claims. It changes city flags only. It cannot move funds,
publish claims, configure rates or alter locks. Admin rotation retains both
flags. Claude's default after the audit, revisable by Tim, is a small separate
multisig without a delay; actual members/threshold remain Tim's choice.
Resume fails open if the guardian is compromised: it can lift its own pause,
while replacement requires the seven-day admin process. Claude's default keeps
resume; a separate pause-only key is an alternative Tim may choose later.

The separate registrar immediately registers ratified climbs and admits hills
(`registerRatifiedClimb`, `initHillBond`) and has no other authority. Its
registration supplies the canonical city as the sole read-only remaining
account, preserving the legacy admin instruction ABI. Admin rotation/revocation
uses the seven-day process. Both roles are separate from admin, publisher,
backend, each other, the admin vault and its members. Preflight rejects member
collisions before creation, AddMember or handoff. Raw legacy/Squads transactions
can bypass operator policy; status must report such conflicts as unsafe.

Cancellation, notice/cancel-notice, materialization, harvesting, eligible
withdrawal and cash claims from already-published sets remain available during
either pause. DUNG claims wait during settlement pause, even when their
172,800-second wait has elapsed; intake pause alone does not hold them.
Existing locks still apply.

This is an upgradeable system. A threshold coalition can approve different
code or Squads settings after the current wait. These tools reject delay
reductions, config authorities, spending limits, arbitrary vault transfers and
admin transfers away from this vault. That operator policy is not an immutable
on-chain prohibition on all future software or settings. Inspect every Active and Approved proposal as well as the actual
settings and both authorities; do not infer them from a multisig address.
See [Squads account semantics](https://docs.squads.so/main/development/reference/accounts)
and [configuration execution](https://github.com/Squads-Protocol/v4/blob/main/programs/squads_multisig_program/src/instructions/config_transaction_execute.rs).

## Existing accounts and destination inventory

The upgrade inventory in the composed runbook requires fresh Stage1 financial
state: every known Stage1 type except city/recipient must be absent, including
retired receipts/indices and the devnet pool singleton. Populated older accounts
need compatible migrations beyond this city migration. An active publisher on
an already handed-off legacy city needs a separately reviewed delayed operation;
the current general `propose-admin` gate remains strict.

The composed release keeps one unreleased `0x4D` ABI above `0x4C`.
The city is 963 bytes including its discriminator. The permissionless
`migrateStage1City` accepts exactly the recorded layouts: 881-byte initial,
897-byte DUNG, 914/915-byte governance rounds, 931-byte merged and 963-byte
current. It preserves the common 881 bytes and explicitly relocates historical
role fields when DUNG fields occupy their former offsets. Existing DUNG policy,
guardian and pauses survive; absent roles/policy initialize unset. Unknown
lengths, owners and discriminators fail. Any payer can fund the exact rent delta;
calling it on the current layout is an asserted no-op.

After upgrade, wait for a later finalized slot before migration or new handlers.
An existing city must migrate before typed Stage1 calls. A fresh city needs no
migration. The composed runbook supplies the single `0x4C` to `0x4D` advance
procedure; ordinary operators keep their current-version gate.

| Surface | Writable value accounts / permitted destination |
|---|---|
| Guardian pause/resume; admin guardian/registrar/publisher rotation | City config only; no token account or payment destination |
| City, asset, hill and devnet-pool initialization | Vault pays rent to the exact program/custody PDAs; no backing debit |
| ProgramConfig administration | Config only; old config migrations may pay its rent from the admin vault |
| Permissionless city migration | Explicit payer pays rent to the same city PDA |
| Cancellation and completed withdrawal | Owner-bound token destination; lot/request/custody constraints remain enforced |
| Harvest and claims | Existing fixed earnings/owner-reserve custody and registered recipient constraints; unchanged in this slice |
| Loader upgrade | Reviewed buffer/code only; excess buffer rent returns to vault index 0 |
| Loader extension | Explicit payer funds program storage; code and upgrade authority remain unchanged |

### Legacy helper isolation

No legacy helper needed a behavior change. The inventory is tested in default
and devnet builds, not just by the localnet feature:

| Backend-authorized helper | Legacy account boundary |
|---|---|
| `adminSeedPendingRewards` | Typed `Vault` / `VaultActivation` |
| `adminOverrideOpenSettlementWeek` | Typed `Vault` |
| `adminOverrideStakeEligibility` | Typed `VaultStake` |
| `adminSeedVaultCompletionSummary` | Typed `Vault` |
| `adminReplaceVaultLeaderboard` | Typed `Vault` / `VaultLeaderboard` |
| `adminActivateVault` | Typed `Vault` / `VaultActivation` |
| `adminBackfillVaultActivation` | Program owner, nonempty bytes and canonical vault PDA checks; activation init/PDA constraints before write |

Native tests reject all fifteen canonical Stage 1 account discriminators (plus
the devnet singleton) as legacy helper/config types. Runtime tests substitute
actual locally created Stage 1 accounts into every listed helper and verify
rejection plus unchanged bytes and season anchor. Stage 1 timing uses its own
immutable city anchor and Solana Clock, not a legacy Vault clock. The synthetic
`setTestLstRate` dispatch exists only in the isolated `stage1-localnet` program;
default/devnet dispatch rejects it. These checks do not attest real riding or
provider yield.

## Operator workflow

Run from `protocol/anchor` in the frozen release checkout. Use public keys and
explicit, credential-free HTTP(S) RPC origins in JSON. Replace every placeholder;
never discover an implicit wallet. ProgramConfig must already be initialized.
For initial handoff this CLI requires its current admin to also be the current
upgrade authority, and a fresh multisig with transaction index zero. A deployment
with different authority keys needs a separately reviewed handoff, not a guessed
signer. Fund the vault for the existing admin-paid account rents.

Each action takes `--input`, `--cluster`, `--rpc`, `--program-id`, `--admin`
and a distinct `--fee-payer`. Devnet ELF use on localnet additionally needs
`--program-interface devnet`; default ELF uses `mainnet`. Plan mode reads no
keypair. Submission re-reads finalized state, checks the plan digest, signs
once, verifies signatures in simulation, sends those identical bytes, and
checks the finalized outcome. If state changes, review a new plan. An ambiguous
send needs chain reconciliation, not an automatic rebuilt transaction.

```bash
# Example: test-key devnet rehearsal. All values below require explicit choice.
node --loader ts-node/esm scripts/stage1_governance.ts \
  --mode plan --action '<ACTION>' --input '<INPUT_JSON>' \
  --cluster devnet --rpc '<CREDENTIAL_FREE_DEVNET_ORIGIN>' \
  --program-id '<PROGRAM_PUBLIC_KEY>' --admin '<CURRENT_ADMIN_OR_VAULT_PUBLIC_KEY>' \
  --fee-payer '<FEE_PAYER_PUBLIC_KEY>' > '<NEW_PLAN_JSON>'

# Review the complete plan, decoded proposal, state hashes and digest first.
# Repeat the exact arguments above, changing mode to submit, and add:
# --plan '<REVIEWED_PLAN_JSON>' --digest '<REVIEWED_DIGEST>'
# --fee-payer-keypair '<EXPLICIT_TEST_PAYER_FILE>'
# plus only the signer paths required by that action, listed below.
```

All input objects contain `multisig: "<MULTISIG_PUBLIC_KEY>"`. Derive that PDA
from the explicit create key with `squads.getMultisigPda({createKey})`; derive
the vault with `getVaultPda({multisigPda,index:0})`. Verify both in the plan.

| Action | Additional JSON input | Additional submit signer |
|---|---|---|
| `create` | `createKey`, `creator`, `members: ["<MEMBER_1>", "<MEMBER_2>", "..."]`, `threshold: <TIM_CHOSEN_INTEGER>` | `--create-key-keypair`, `--creator-keypair` |
| `handoff` | Reviewed `binaryLength` that fits the already extended ProgramData | `--admin-keypair` for the explicit current authority |
| `check` | Optional `transactionIndex` as a decimal string | None; use plan mode |
| `extend-program` | `binaryLength` in bytes; run before handoff | Fee payer; checked extension also requires `--admin-keypair` for the current upgrade authority |
| `migrate-city` | None | Fee payer only |
| `propose-admin` | `member`, `transactionIndex`, `instructions` | `--member-keypair` |
| `propose-upgrade` | `member`, `transactionIndex`, `buffer`, `binarySha256`, nonempty `migrationNotes` | `--member-keypair` |
| `propose-config` | `member`, `transactionIndex`, `actions` | `--member-keypair` |
| `approve` | `member`, `transactionIndex`, reviewed `transactionSha256`; upgrades also `binarySha256` | `--member-keypair` for each distinct voter |
| `reject` | `member`, `transactionIndex`, reviewed `transactionSha256`; Active proposal | `--member-keypair` for each rejection voter |
| `cancel` | Same inputs; Approved proposal, including stale Approved | `--member-keypair` for each cancellation voter |
| `execute` | Approval inputs plus `kind: "vault"` or `"config"` | `--member-keypair` |

Admin `instructions` use `instructionJson(ix)` from `stage1_operator.ts`:
`{program, keys:[{key,signer,writable}], data:<BASE64>}`. Construct each from
the release IDL, using the vault as the only inner signer. Plans decode the
stored proposal again for voters/executors. Large operations must be split
into separately reviewed proposals; this transport does not admit lookup
tables or ephemeral signers. Config actions are only
`{kind:"add-member",key}`, `{kind:"remove-member",key}` and
`{kind:"threshold",threshold}`. Preserve a usable threshold throughout the
reviewed transition.

Before removing a signer, run `check` and identify every Active or Approved
proposal they created or approved, including stale Approved proposals. Reject
Active proposals and cancel Approved ones with enough current member votes to
reach terminal `Rejected`/`Cancelled` status. One vote is not cancellation.
Review the stored transaction hash even when the tool marks its payload
unadmitted. Confirm every affected proposal is terminal before proposing,
approving and executing the delayed removal; the tool enforces this order at
each stage. Removing a member does not revoke their prior approvals, and a
stale Approved proposal can still execute. Recheck pending proposals after
removal. Stale Active proposals are permanently unapprovable under Squads and cannot
be rejected. They remain listed but do not block removal or ordinary operations.
The public check ignores stale Active payloads, and fails on **every stale
Approved proposal**, including an otherwise admitted harmless call.

Extend ProgramData **before handoff** for the reviewed upgrade size and any
explicitly budgeted capacity. Handoff checks that `binaryLength` fits. The
operator refuses extension once the vault owns the program: its vault path
admits only Upgrade. Agave 2.1.21 supports legacy permissionless unchecked
`ExtendProgram` (tag 6); our prehandoff rule is operator policy, not an on-chain
restriction of that legacy instruction. On the versioned Agave 2.3.4 path,
activation of feature `2oMRZEDWT2tqtYMofhmmfQ8SsjqUFzT6sYXppQDavxwz`
requires `ExtendProgramChecked` (tag 9, current authority signature). The tool
reads and binds that finalized feature account rather than inferring behavior
from a cluster name. Checked extension has unit-level instruction/state proof;
the pinned 2.1.21 local runtime exercises unchecked extension. See the
[published loader interface](https://github.com/anza-xyz/solana-sdk/blob/617f74e0d0a129d5abaae524861122250a634c1d/loader-v3-interface/src/instruction.rs)
and [2.3.4 runtime](https://github.com/anza-xyz/agave/blob/v2.3.4/programs/bpf_loader/src/lib.rs).

Deployable builds require the crate's `no-idl` feature. Anchor 0.29 IDL
instructions return `IdlInstructionStub` (1000); canonical IDLs are distributed
from the reviewed repository. `check` verifies actual running dispatch with
an unsigned, account-free IDL-tag simulation. Enabled dispatch returns 102;
unknown failures fail status. Historical 1c bootstrap permits authority
handoff and only the reviewed delayed upgrade while IDL dispatch remains
enabled. Ordinary administration is blocked until IDL dispatch is disabled
and any city migration completes. Status stays false throughout that partial
setup; finalized upgrade checks code bytes and the actual disabled-IDL probe.

Upload a buffer with an explicit test payer/buffer authority using
`solana program write-buffer <ELF> --url <RPC> --keypair <TEST_PAYER_FILE>
--buffer <NEW_BUFFER_FILE> --buffer-authority <TEST_BUFFER_AUTHORITY_FILE>`.
Transfer its buffer authority to the reviewed vault before proposing, using
`solana program set-buffer-authority <BUFFER_PUBLIC_KEY> --url <RPC>
--buffer-authority <TEST_BUFFER_AUTHORITY_FILE> --new-buffer-authority
<VAULT_PUBLIC_KEY> --fee-payer <TEST_PAYER_FILE>`.
These upload transactions are separate from the governance transaction.
Hash the exact ELF; review buffer bytes and capacity. `propose-upgrade` refuses
insufficient ProgramData capacity; reserve that capacity before handoff.
Approvals bind the stored transaction hash and binary hash. Execution checks
chain time and verifies the finalized code hash, unchanged vault authority and
consumed buffer, then waits for a later finalized slot before migration can
call the new code. Publish migration notes alongside the proposal; the CLI plan
contains them, but Squads does not store those prose notes in the loader message.

The public `check` reports members, threshold, permissions, delay, config
authority, spending limits, actual loader authority, shared admin, version,
guardian, both pauses, IDL dispatch and pending city migration. It lists and
decodes **every Active and Approved proposal**, including stale Approved ones,
with creator, voters, digest, calls/actions, admission reason and approval time.
Any pending membership/threshold/time-lock change or unadmitted payload makes
`sevenDayGovernanceApplied=false`. An admitted config change may still proceed
through its reviewed delayed path, but other hazardous proposals that can
still execute must first be rejected/cancelled. `check --input` with an optional transaction index reports
an unadmitted payload and its reason instead of throwing. A false
`sevenDayGovernanceApplied` means the full setup is not currently satisfied. A missing city is reported absent.

## Rehearsals and launch gates

The local runner pins Agave 2.1.21 and the SHA-256 values in
`tests/fixtures/stage1_governance/squads-provenance.json`. Squads was captured
read-only from mainnet: program `SQDS4ep65T869zMMBKyuUq6aD6EgTu8psMjkvj52pCf`,
last deploy slot 302582236, immutable upgrade authority at capture. The small
config dump is retained alongside its provenance for repeatable local tests.
CI runs the default and devnet governance suites with that retained config and
the hash-checked immutable program dump. Both start from the exact 1c ELF
built by `build-stage1-initial.py` in a separate Cargo target and pass it via
`--initial-program`, exercising real old-city bytes and migration. Reproduce
the binary using `solana program dump --url <MAINNET_RPC> <SQUADS_ID> <FILE>`
and the config using `solana account --url <MAINNET_RPC>
BSTq9w3kZwNwpBXJEvTZz2G9ZTNyKBvoSeXMvwb4cNZr --output json > <CONFIG_JSON>`.
Do not silently replace the pinned capture when a hash differs.

```bash
python3 scripts/test-stage1-governance.py --build default \
  --wallet '<DISPOSABLE_LOCAL_WALLET>' --squads-program '<PINNED_SQUADS_ELF>' \
  --squads-config '<PINNED_CONFIG_JSON>' --initial-program '<EXACT_1C_ELF>'
python3 scripts/test-stage1-governance.py --build devnet \
  --wallet '<DISPOSABLE_LOCAL_WALLET>' --squads-program '<PINNED_SQUADS_ELF>' \
  --squads-config '<PINNED_CONFIG_JSON>' --pool-program '<VERIFIED_SPL_TEST_ELF>' \
  --initial-program '<EXACT_1C_ELF>'
# Separate real 0x4D -> 0x4E governance cutover (build-stage1-initial.py --previous-version):
python3 scripts/test-stage1-governance.py --build default --version-upgrade \
  --wallet '<DISPOSABLE_LOCAL_WALLET>' --squads-program '<PINNED_SQUADS_ELF>' \
  --squads-config '<PINNED_CONFIG_JSON>' --initial-program '<EXACT_0x4D_ELF>'
```

Snapshot replay preserves actual account bytes. Upgrade, admin and config
execution are probed at approval +604799 (reject) and +604800 (accept), then
committed on a normally ticking local validator. This is accelerated local
evidence, not seven days elapsed on devnet. The inherited process supervisor
stops its own validators and requires zero owned replay ledgers on every exit.

The **future authorized devnet rehearsal** uses dedicated test keys and the
devnet artifact guard. Create/verify the multisig, atomically hand off both
authorities, and publish a harmless admin proposal and reviewed upgrade.
Have distinct members review and approve each. Record finalized threshold
timestamps and schedule execution at or after +604800 seconds. Observe early
refusal, leave the real devnet clock running for the full seven days, then
execute and verify finalized settings/code. Cancel the departing signer’s open
proposals, then repeat a signer/threshold change through its delayed config
path. Pause immediately with the guardian, exercise
owner cancellation/eligible exit, and resume through an approved delayed admin
proposal. Keep the 1c provider, ordinary epoch and client-release gates; this
governance rehearsal cannot replace them.

Before mainnet, Tim confirms members, threshold, separate guardian, scoped
publisher, fee payer, rent budget and notice. Use independently controlled
hardware wallets with verified recovery arrangements. Publish the frozen
commit, ELF SHA-256, buffer and ProgramData addresses, migration instructions,
approval time and scheduled execution time. Independently inspect the exact
hardware-wallet transaction message and both authority changes. This CLI's
submit transport accepts explicit test keypair files, not hardware devices:
use a reviewed hardware signing path for mainnet; never export hardware keys
to make these examples work. Audit, release approval and real-world rehearsal
remain required. A draft PR or a local timing test is not mainnet readiness.

## Backer notice

**TIM:** Supply the rider-facing notice explaining that seven days announces
an upgrade but is shorter than the 26-week lock and four-week notice, so a
backer may be unable to exit before an approved change takes effect.
