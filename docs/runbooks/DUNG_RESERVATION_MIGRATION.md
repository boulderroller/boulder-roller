# DUNG Reservation Migration

This runbook upgrades an existing `DungMintState` to the 130-byte,
full-liability reservation policy. It is a one-time protocol migration. It is
not a settlement crank and must run while all state-changing economy writers
are paused.

The current deployment also bootstraps the exact program-version gate from
V4-A `0x40` to `0x41`. The deployed `0x40` binary cannot enforce the gate that
does not yet exist, so this first transition is one indivisible paused rollout:
deploy the reviewed binary, complete every required account migration, advance
the version byte, validate finalized state, and only then resume matching
clients. Do not publish `0x41` runtime expectations while the live byte remains
`0x40`.

## Invariants

The migration may start from:

- 121 bytes: legacy state with no explicit reservation.
- 129 bytes: claim-only predecessor with `community_reserved` but no policy
  marker.
- 130 bytes: current state; reruns are accepted only when the reservation is
  already exact.

The target state must satisfy all of the following:

- `reservation_policy_version == 1`.
- `community_reserved` equals all unclaimed `VaultStake.rewards_earned` plus
  every Vault's Record Royalty, staker, and Local Legend carry.
- The original account prefix is byte-for-byte unchanged.
- Stored authority equals the ProgramConfig admin and the stored bump equals
  the canonical PDA bump.
- An unversioned state still has `current_emission_rate_bps == 10000`.
- Minted plus reserved supply stays inside both the global and Community caps.

The ProgramConfig admin authorizes the migration. A separate, powerless payer
funds the address lookup table, transaction fee, and account rent. Never use
the admin or program upgrade authority as the payer.

The same signer separation applies to `advance_program_version.ts`: the
ProgramConfig admin authorizes the one-byte transition, while the powerless
payer pays the fee. The script rejects a shared keypair and verifies that byte
72 is the only changed ProgramConfig byte.

## Scope

`protocol/anchor/scripts/migrate_dung_liability_reservation.ts` provides the
approved devnet keypair flow. Mainnet must use a separately reviewed
Squads/external-signer transaction transport that preserves the same message,
inventory hash, and plan-hash gates.

Run commands from `protocol/anchor` with the reviewed program artifact and IDL.
Set environment-specific values explicitly:

```bash
export CLUSTER_URL='<finalized RPC URL>'
export PROGRAM_ID='<Boulder Rollers program id>'
export ADMIN_KEY='<ProgramConfig admin keypair path>'
export PAYER_KEY='<powerless fee-payer keypair path>'
export PAYER_PUBKEY='<fee-payer public key>'
```

## Procedure

1. From the repository root, bind the generated clients and reviewed ABI to
   the exact manifest transition **before** building the release artifact:

```bash
python3 protocol/scripts/check_program_version.py --base-ref origin/main
cd protocol/anchor
anchor build
COPYFILE_DISABLE=1 anchor test --skip-build
shasum -a 256 target/deploy/boulder_rollers.so
```

   Record the artifact SHA-256. The transaction test must initialize the
   manifest's current version; a stale pre-advance binary is not a release
   artifact. Apply
   `backend/supabase/migrations/20260714_127_dung_reservation_observability.sql`
   before deploying the upgraded indexer.

2. Prepare the inventory address lookup table before the writer pause. This
   operation may be repeated if the later paused census contains new accounts.

   Run the upgrade preflight first. This mode validates repository, program-ID,
   deploy-keypair, runtime configuration, and RPC reachability without
   pretending the intentionally old live account layouts are already current:

```bash
./scripts/preflight.sh --rpc "$CLUSTER_URL" --upgrade-preflight
```

   The existing-program path verifies the live program address and upgrade
   authority, requires a distinct fee payer, and records the built artifact
   SHA-256. It does not require the random keypair emitted in `target/deploy`;
   Solana upgrades address the already deployed program directly.

```bash
NODE_OPTIONS='--loader ts-node/esm --no-warnings' node \
  scripts/migrate_dung_liability_reservation.ts \
  --cluster "$CLUSTER_URL" \
  --program-id "$PROGRAM_ID" \
  --payer "$PAYER_KEY" \
  --payer-pubkey "$PAYER_PUBKEY" \
  --prepare-alt
```

Record the returned lookup-table address.

3. Pause settlement, stake and unstake, Vault creation, reward collection, and
   every other operation that can create a census account or change a claim or
   carry. Record the pause evidence and slot.

4. Deploy the upgraded program while writers remain paused. Upgraded
   settlement fails closed until policy version 1 is present.

   Bind the approved Settlement Clock v2 cutover and grow ProgramConfig from
   325 to 334 bytes with the canonical admin signer and distinct transaction
   fee payer. The instruction's existing ABI uses the admin as the nine-byte
   rent source; the admin is not the transaction fee payer.

```bash
SOLANA_CLUSTER="$CLUSTER_URL" \
NODE_OPTIONS='--loader ts-node/esm --no-warnings' node \
  scripts/configure_program_mints.ts \
  --cal-mint '<CAL_MINT>' \
  --dung-mint '<DUNG_MINT>' \
  --settlement-clock-cutover '<APPROVED_CUTOVER>' \
  --admin-keypair "$ADMIN_KEY" \
  --fee-payer "$PAYER_KEY"
```

5. Run the script read-only with the prepared lookup table. Review the exact
   stake count, Vault count, liability total, nonzero claims and carries,
   inventory manifest hash, account authority, bump, and legacy emission rate.

```bash
NODE_OPTIONS='--loader ts-node/esm --no-warnings' node \
  scripts/migrate_dung_liability_reservation.ts \
  --cluster "$CLUSTER_URL" \
  --program-id "$PROGRAM_ID" \
  --payer-pubkey "$PAYER_PUBKEY" \
  --lookup-table '<ALT_ADDRESS>'
```

If lookup-table coverage is incomplete, return to step 2. Do not continue by
dropping accounts from the census.

6. Simulate the exact paused census. Replace all placeholders with the values
   from step 5.

```bash
NODE_OPTIONS='--loader ts-node/esm --no-warnings' node \
  scripts/migrate_dung_liability_reservation.ts \
  --cluster "$CLUSTER_URL" \
  --program-id "$PROGRAM_ID" \
  --authority "$ADMIN_KEY" \
  --payer "$PAYER_KEY" \
  --payer-pubkey "$PAYER_PUBKEY" \
  --lookup-table '<ALT_ADDRESS>' \
  --expected-count '<STAKE_COUNT>' \
  --expected-vault-count '<VAULT_COUNT>' \
  --expected-total '<LIABILITY_BASE_UNITS>' \
  --expected-manifest-sha256 '<MANIFEST_SHA256>' \
  --operations-paused \
  --simulate-only
```

The simulation must have no program error and must fit the packet and compute
limits. Review and record the returned migration plan SHA-256.

7. Execute the same message with the reviewed plan hash. Any census drift,
   lookup-table drift, plan drift, signature mismatch, or simulation failure
   must abort before submission.

```bash
NODE_OPTIONS='--loader ts-node/esm --no-warnings' node \
  scripts/migrate_dung_liability_reservation.ts \
  --cluster "$CLUSTER_URL" \
  --program-id "$PROGRAM_ID" \
  --authority "$ADMIN_KEY" \
  --payer "$PAYER_KEY" \
  --payer-pubkey "$PAYER_PUBKEY" \
  --lookup-table '<ALT_ADDRESS>' \
  --expected-count '<STAKE_COUNT>' \
  --expected-vault-count '<VAULT_COUNT>' \
  --expected-total '<LIABILITY_BASE_UNITS>' \
  --expected-manifest-sha256 '<MANIFEST_SHA256>' \
  --expected-plan-sha256 '<PLAN_SHA256>' \
  --operations-paused \
  --execute
```

8. Keep writers paused through finalized verification. The script rereads at
   or after the confirmation slot and checks the same census, manifest,
   reservation, preserved prefix, policy version, and supply caps.

9. With every required on-chain account migration finalized, advance the live
   ProgramConfig compatibility byte. This is deliberately last: `0x41` means
   the deployed program and its migrated state are ready for `0x41` clients.

```bash
NODE_OPTIONS='--loader ts-node/esm --no-warnings' node \
  scripts/advance_program_version.ts \
  --rpc "$CLUSTER_URL" \
  --program-id "$PROGRAM_ID" \
  --admin-keypair "$ADMIN_KEY" \
  --fee-payer "$PAYER_KEY"
```

   Record the finalized signature, before/after slots, ABI SHA-256, account
   length, and `changed_offsets: [72]`. A rerun is read-only and succeeds only
   when the live byte is already the manifest's current version.

10. Run `scripts/validate_deployment.ts`, start the matching backend and
upgraded indexer, and verify
   `indexed_supply.community_reserved` and
   `indexed_supply.reservation_policy_version` match chain state. Only then
   resume writers.

## Failure Handling

Before submission, correct the cause and restart from the read-only census.
After a confirmed policy-v1 migration or `0x41` version advance, do not roll
back to `0x40` code or code that can settle without full-liability reservation.
Keep writers paused and deploy a forward fix. A repeated migration is valid
only when the exact liability and existing reservation still match. A failed
version advance leaves the live byte unchanged; diagnose it while writers
remain paused rather than bypassing the gate.
