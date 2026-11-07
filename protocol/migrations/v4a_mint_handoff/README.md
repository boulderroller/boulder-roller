# V4-A to V4-B Mint Authority Handoff

This migration program is the bounded devnet bridge for
`boulderroller-v2-4crx.11`. The existing CAL and DUNG mint authorities are
V4-A PDAs, so a wallet-side SPL Token `set-authority` command cannot move them
to a fresh V4-B program.

The bridge can do exactly one atomic operation:

- it runs only at the retired V4-A program address;
- it requires the current V4-A admin authority signature;
- it accepts only the exact current devnet CAL and DUNG mints;
- it requires both current mint authorities to equal the exact V4-A PDAs;
- it requires a distinct, finalized executable target with an initialized
  V4-B ProgramConfig PDA owned by that target;
- it requires that config to bind the exact admin and backend authorities,
  program version `0x4B`, CAL and DUNG mints, and target authority bumps;
- it derives both destination authorities from that target program ID; and
- it transfers both authorities in one transaction, which rolls back as a
  unit if either transfer fails.

After success, the V4-A PDAs no longer own either mint, so the bridge cannot
repeat the handoff. This program retires the old V4-A runtime; it must never be
deployed at the fresh V4-B address.

## Build and verify

```bash
cargo test --locked --manifest-path protocol/migrations/v4a_mint_handoff/Cargo.toml
cargo build-sbf \
  --manifest-path protocol/migrations/v4a_mint_handoff/Cargo.toml \
  --sbf-out-dir protocol/migrations/v4a_mint_handoff/artifacts
shasum -a 256 \
  protocol/migrations/v4a_mint_handoff/artifacts/v4a_mint_handoff.so
```

Generated binaries, build directories, and keypairs are ignored. Never commit
a generated keypair. Record the reviewed bridge SHA-256 and live deployment
signature in the Lane A evidence packet.

## Authorized execution order

Execution is forbidden until the V4-B truth amendment and rider-visible
captures have Tim's explicit approval.

1. Pause all V4-A writers.
2. Deploy the fresh V4-B program, initialize ProgramConfig with separate
   fee-payer, admin/upgrade-authority, and backend-authority keys, and run its
   one-time `configure_mints` instruction for the existing CAL and DUNG mints.
3. Build the bridge from the locked source and record its SHA-256.
4. Upgrade the old V4-A program address to the reviewed bridge binary, using
   the existing admin/upgrade authority and the powerless fee payer.
5. Run `protocol/anchor/scripts/execute_v4a_mint_handoff.mjs` without
   `--send`. It checks the deployed bridge bytes, target program, target
   ProgramConfig, current authorities, key-role separation, and exact
   destination PDAs.
6. Re-run with `--send`, then independently read both finalized mint accounts
   and validate the fresh V4-B deployment before resuming writers.

The execution command requires explicit paths and a fresh V4-B program ID:

```bash
node protocol/anchor/scripts/execute_v4a_mint_handoff.mjs \
  --rpc https://api.devnet.solana.com \
  --target-program '<fresh V4-B program ID>' \
  --admin-keypair '<admin keypair path>' \
  --fee-payer '<fee-payer keypair path>' \
  --bridge-artifact \
    protocol/migrations/v4a_mint_handoff/artifacts/v4a_mint_handoff.so
```

Add `--send` only for the approved, reviewed handoff.
