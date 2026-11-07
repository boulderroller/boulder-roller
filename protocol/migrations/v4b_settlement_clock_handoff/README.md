# V4-B Settlement Clock Lineage Handoff

This migration program is the bounded repair for the fail-closed production
cutover gate in `boulderroller-v2-4crx.11`.

Fresh V4-B initialization intentionally creates a V2-only clock at
`1704110400`. The live Boulder Roller database already has immutable V1
settlement history and the ratified V2 cutover `1784548800`. Projecting the
fresh clock would renumber that history, so the database guard rejected the
indexer snapshot before any writer resumed.

The bridge performs one exact lineage adoption:

- it runs only at the finalized V4-B program address;
- it requires the exact admin signature and ProgramConfig/VaultCounter PDAs;
- it requires ProgramConfig version `0x4B`, exact admin/backend authorities,
  exact CAL/DUNG mints, and the fresh V2-only anchor;
- it requires the V4-B VaultCounter to remain zero;
- it writes only the settlement cutover bytes, from `1704110400` to the
  already-ratified production value `1784548800`; and
- a replay at the exact target value is idempotent, while every other clock or
  runtime identity fails closed.

This is a temporary upgrade bridge. After its single finalized transaction,
restore the reviewed canonical V4-B binary and independently verify both the
ProgramConfig cutover and deployed program bytes before applying the database
lineage migration or resuming the indexer.

## Build and verify

```bash
cargo test --locked \
  --manifest-path protocol/migrations/v4b_settlement_clock_handoff/Cargo.toml
cargo build-sbf \
  --manifest-path protocol/migrations/v4b_settlement_clock_handoff/Cargo.toml \
  --sbf-out-dir protocol/migrations/v4b_settlement_clock_handoff/artifacts
shasum -a 256 \
  protocol/migrations/v4b_settlement_clock_handoff/artifacts/v4b_settlement_clock_handoff.so
```

Generated binaries, build directories, and keypairs are ignored. Record the
reviewed bridge SHA-256, bridge deployment signature, handoff signature,
canonical restore signature, finalized ProgramConfig slot, and restored
canonical binary SHA-256 in the Lane A evidence packet.

## Authorized execution order

1. Keep the API/indexer writers paused and prove the V4-B VaultCounter is zero.
2. Build and test this bridge from locked source.
3. Deploy it temporarily at the exact V4-B address.
4. Run `execute_v4b_settlement_clock_handoff.mjs` without `--send` and review
   its finalized plan.
5. Re-run with `--send`.
6. Restore the canonical V4-B binary immediately.
7. Verify finalized ProgramConfig, exact deployed bytes, and zero VaultCounter.
8. Apply the database lineage migration and resume the indexer only after its
   snapshot reports zero decode, write, and fetch failures.
