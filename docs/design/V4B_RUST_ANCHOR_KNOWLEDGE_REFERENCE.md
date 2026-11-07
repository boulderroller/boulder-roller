# V4-B Rust / Anchor / Solana Knowledge Reference

**Audience:** the protocol agent picking up 0uv8 (Climb/Vault on-chain surface split), or a mobile/backend agent scaffolding it while they are iced.

**Scope:** external knowledge domain only. Repo-internal scope, blast radius, and migration/test plans are in sibling research docs. This doc compiles "what the broader Solana/Anchor community has learned the hard way" for every decision V4-B will touch.

**Grounding context (repo-internal):** V4-A is deployed at program `HsPhhMukUKu641e9hDJUJJW4chvF5EXYzuG2xBwMrnst`. Anchor 0.29.0 is pinned. The monolithic `Vault` struct (`protocol/anchor/programs/boulder_rollers/src/lib.rs:2987`) must be decomposed into `Climb` + `Vault` per PROTOCOL_TRUTHS §2.1–2.2 and PROTOCOL_ALIGNMENT_FIX_PLAN P1. The existing V4-A code already demonstrates realloc patterns (e.g. `ProgramConfig::SIZE_V2` realloc at `lib.rs:4622`) and discrete settlement flow; this doc is the external catch-up layer around those idioms.

**Ground rule:** every external claim cites a URL. "Community consensus" and "one blog post" are distinguished where it matters.

---

## 1. Anchor framework state

**Pinned in this repo:** `anchor-lang = 0.29.0`, `anchor-spl = 0.29.0` (`protocol/anchor/programs/boulder_rollers/Cargo.toml:16-17`). The `[toolchain]` entry in `Anchor.toml` also hard-pins `anchor_version = "0.29.0"`. CI (`solana-ci.yml`) installs Solana 1.18.17 per the workspace Cargo.toml comment.

**Current Anchor releases:**
- **0.29.0** (target of this repo) — release notes: https://www.anchor-lang.com/docs/updates/release-notes/0-29-0
- **0.30.0** (2024-04-15) — https://www.anchor-lang.com/docs/updates/release-notes/0-30-0
- **0.30.1** — https://www.anchor-lang.com/docs/updates/release-notes/0-30-1
- **0.31.0** (2025-03-09) — https://www.anchor-lang.com/docs/updates/release-notes/0-31-0
- **0.31.1** (2025-04-20) — most recent stable

**0.29 → 0.30 breaking changes (the ones that matter if we ever upgrade):**
- **IDL format rewritten.** `idl-build` feature is now required in `Cargo.toml`. This repo already adds that feature block (`Cargo.toml:13`), so the future bump is less painful than average. Details: https://www.anchor-lang.com/docs/updates/release-notes/0-30-0 and https://blog.chalda.cz/posts/anchor-idl/
- **`anchor idl convert` CLI** converts legacy (pre-0.30) IDLs; in 0.31 the conversion runs automatically for most commands. Source: https://www.anchor-lang.com/docs/updates/release-notes/0-31-0
- **Discriminator length was fixed at 8 bytes through 0.30; 0.31 introduces custom discriminator support** via `#[discriminator]`. Source: https://github.com/solana-foundation/anchor/issues/3097 and https://github.com/solana-foundation/anchor/pull/2728

**0.29-specific notes from the 0.29 release page:**
- Min Solana version raised to 1.16.
- `ctx.bumps` is now a generated struct, not a `BTreeMap<String, u8>` (type-safe bump access).
- Binary size reduction ~36% vs 0.28.
- Docker image renamed: `projectserum/build` → `backpackapp/build`.
- `[toolchain]` section in `Anchor.toml` (already used in this repo).
- Source: https://www.anchor-lang.com/docs/updates/release-notes/0-29-0

**Rust toolchain.** The repo leaves this implicit to Anchor 0.29's pin. Anchor 0.29 ships against Solana 1.16–1.18; using a Rust toolchain newer than ~1.75 can trigger `rustc` features that the Solana BPF toolchain hasn't absorbed, producing obscure `cargo-build-sbf` errors. When CI wedges, check the Rust version first. Source: https://github.com/solana-foundation/anchor/issues/3044 (tracks 2.0-related breakage more broadly).

**Agave 2.0 awareness.** Agave is the post-migration validator name; several `solana-*` crates were renamed to `agave-*`. Anchor 0.31+ has the stack-usage improvements needed for Solana v2 `init`-heavy builds. If the hackathon ever targets mainnet via an Agave 2.0 validator, expect a minor toolchain thrash — but this is not a V4-B blocker. Sources: https://github.com/anza-xyz/agave/wiki/Agave-v2.0-Transition-Guide, https://www.helius.dev/blog/agave-v2-update

**Recommendation for V4-B:** do **not** bump Anchor mid-sprint. 0.29 is stable, the repo is healthy on it, and 0.30's IDL-format rewrite would burden the sibling backend decoder workstream (WS-2a in PROTOCOL_ALIGNMENT_FIX_PLAN). Bump in a separate epic after V4-B lands.

---

## 2. Account realloc semantics

Realloc is the single biggest source of foot-guns for any account-shape change — which V4-B is, in the extreme (one struct splits into two). The V4-A code already uses realloc at `ProgramConfig::SIZE_V2` (`lib.rs:4622`, `realloc::zero = true`) so the team has done it once; this section adds the community-surfaced sharp edges around it.

**Mechanics** (sources: https://solanacookbook.com/guides/data-migration.html, https://rareskills.io/post/solana-account-rent, https://dev.to/jacobcreech/how-to-change-account-size-on-solana-55b4):

- `AccountInfo::realloc(new_len, zero_init)` is the raw syscall. Anchor exposes it via the `realloc = <size>, realloc::payer = <signer>, realloc::zero = <bool>` account constraint.
- **Max 10,240 bytes (10 KB) of growth per transaction.** To grow more, call realloc across multiple transactions. An account's absolute max is 10 MiB, but 10 KB is the per-ix growth cap. Source: https://github.com/solana-labs/solana/issues/14694
- **Rent-exempt invariant.** A shrunk account that falls below rent exemption gets garbage-collected — the chain will drain its lamports and wipe it. Any grow must fund the delta from the specified payer. Anchor's `realloc::payer` handles the payer side; the constraint also auto-reclaims lamports on shrink. Source: https://rareskills.io/post/solana-account-rent
- **`realloc::zero`.** If `true`, the new bytes (on grow) are zeroed, and on shrink the freed bytes are zeroed before truncation. If `false`, the growth region contains whatever was previously at that offset in the account's data allocation — which for freshly-grown space should be zero in practice, but **never assume** it is. The 0.29 test at https://github.com/solana-foundation/anchor/blob/master/tests/realloc/tests/realloc.ts exercises the `zero` flag specifically.

**Sharp edges the community has hit:**

1. **`zero = false` on a double-realloc (grow → shrink → grow again)** can surface stale bytes from the previous grow. The first grow wrote `Some(value)` into the new region; shrink removed the logical bytes but the raw account buffer keeps them; the second grow re-exposes them. Rule of thumb: **always `zero = true` unless you can prove the overwrite is total.** Source consensus: https://medium.com/@togunchan/security-vulnerabilities-and-memory-management-in-c-analyzing-realloc-usage-cce81d38b2d2 (generic realloc; same hazard shape), corroborated by the Anchor realloc test linked above which explicitly tests zero-init.

2. **Mid-tx failure leaves the account reallocated.** If your handler reallocs the account then later `require!`s something and errors, Solana's tx atomicity rolls back the data, but the **rent lamports transferred from the payer may or may not roll back depending on where the failure occurred.** Modern Anchor (0.29+) handles this correctly via `realloc::payer` — but raw `invoke`+manual realloc code did not. Treat `realloc::payer` as the only blessed path.

3. **`init-if-needed` + realloc is a reinitialization attack surface.** If an instruction both initializes and reallocs conditionally, an attacker may be able to re-run it on an existing account and reset fields. The Anchor doc explicitly flags this. Sources: https://rareskills.io/post/init-if-needed-anchor, https://solana.com/developers/courses/program-security/reinitialization-attacks — this repo already uses `features = ["init-if-needed"]` (`Cargo.toml:16`), so any new instruction using it needs manual idempotency checks.

4. **128-byte overhead.** Empty accounts are not free. The 128-byte header counts against rent, and realloc-shrinking below that floor is impossible. Source: https://rareskills.io/post/solana-account-rent

5. **Partial writes across multi-tx realloc.** If growing beyond 10 KB requires multiple transactions, the account is in a "halfway grown" state between them. Any concurrent reader sees the partially grown account with zeroed tail. Downstream code must tolerate this — usually by gating on a `version: u8` byte inside the account.

**Safe pattern for struct evolution via realloc** (the V3 `ProgramConfig` pattern this repo already uses, `lib.rs:235-284`):

```rust
// 1. Old struct is V2. New struct is V3 with extra fields appended.
// 2. Migration instruction: realloc = V3::SIZE_V3, realloc::zero = true.
// 3. After realloc, new fields are zero-initialized; treat zeros as "unset"
//    and set explicit values via the same ix (not a follow-up ix).
// 4. Emit a Migrated event for indexer alignment.
// 5. Gate reads by a version byte if mixed populations exist.
```

The repo's own `lib.rs:235-284` is a working exemplar of this pattern. V4-B should extend it, not reinvent.

---

## 3. PDA migration strategies

Three canonical strategies. V4-B is a candidate for each; the fourth research doc in this series should pick the shape.

### Strategy A — Fresh program ID + fresh PDAs

Deploy a new program with a new ID; the old program's state is orphaned (either purged manually or simply ignored). All clients repoint to the new ID.

- **Right when:** account shape changes are invasive, state has no user-owned value (all on-chain state can be reseeded from off-chain truth), and the team controls all clients.
- **This is exactly what V4-A did** (see commit `823d75ee Rotate devnet program id for V4-A fresh lane`). The memory index confirms V4-A was a fresh-lane deployment: `HsPhhMukUKu641e9hDJUJJW4chvF5EXYzuG2xBwMrnst`, with CAL/DUNG mints re-minted.
- **Cost:** clients must redeploy, backend indexer must rewire, devnet state is lost. Gained: zero migration complexity, no "old struct + new struct" coexistence.
- **Source for this pattern as community practice:** https://medium.com/coinmonks/solana-internals-part-2-how-is-a-solana-deployed-and-upgraded-d0ae52601b99 discusses when in-place upgrades break down.

### Strategy B — In-place upgrade + realloc migration ("lazy migration")

Keep program ID; deploy new bytecode; add a migration instruction that reallocs existing accounts to the new shape. Handle mixed old/new populations via version gates until migration is complete.

- **Right when:** the same program ID carries user trust or ecosystem integrations, state volume is too large to reseed, and the account-shape change is a forward-compatible append (not a split).
- **Anchor supports this via `realloc` constraints.** The community pattern is documented at https://solanacookbook.com/guides/data-migration.html.
- **Version tagging is the community-converged idiom:** include a `version: u8` as the first non-discriminator byte; readers dispatch on it. Source: https://solanacookbook.com/guides/data-migration.html

### Strategy C — Hybrid (coexistence period)

New program ID deploys alongside the old. Both are live. A migration window lets users port state from old → new. After the window, old is frozen.

- **Right when:** you need a coexistence period for external integrations (wallets, indexers) to migrate.
- **Cost:** double-maintaining two programs during the window.
- **Marinade did a soft version of this during their v1 → v2** (two program IDs active for a period; case study material is mostly in their GitHub, not blog posts).

### What mainline Solana projects have published

Community case-study material is thinner than the Ethereum equivalent. Concrete published references:

- **Squads Protocol v1 → v4** — v4 is a clean redeploy with new account shape; Squads documents a `MultisigCreate v1 → v2` SDK migration path at https://docs.squads.so/main (indicating they went hybrid at the SDK layer, not full in-place). Source: https://github.com/Squads-Protocol/v4
- **Jito Solana** — their staking vault integration shows the pain of integrating programs with versioned account shapes from the outside. Source: https://medium.com/@chajesse/the-struggle-of-integrating-jito-staking-vault-into-my-solana-program-3195b5b3c7a5
- **Metaplex Token Metadata** — Metadata and MasterEdition accounts were designed split-from-day-one, so Metaplex's published pattern is mostly "how to keep them split cleanly" rather than "how to migrate one into two." Still useful as reference for the *target* shape. Source: https://developers.metaplex.com/token-metadata
- **Marinade / Lido on Solana** — both use multisig-gated upgrade authorities (Serum Multisig in Lido's case, 4/7 threshold). Lido's admin pattern is documented at https://docs.solana.lido.fi/administration/

**Community checklist for a program migration** (synthesized from the above):

1. Pin Anchor + Solana toolchain before the redeploy, re-pin again after.
2. Land the new struct + new discriminators in a separate program (Strategy A) or behind a version byte (Strategy B).
3. Land the migration instruction and test it on localnet against captured devnet account snapshots.
4. Dry-run on devnet first. Always. No exceptions.
5. Prepare a rollback: for Strategy A, rollback is "repoint clients back to old program"; for Strategy B, the new program must refuse to load if `version` byte is unrecognized, not crash. Source pattern: https://dev.to/ohmygod/solana-program-security-checklist-14-critical-checks-before-you-deploy-to-mainnet-2d66

### When each strategy is right for V4-B

- V4-A already used Strategy A (fresh program ID). Devnet state is reseedable. No external integrations exist yet. **Strategy A is the path of least resistance for V4-B too** unless sibling research flags a blocker.
- Strategy B would be appropriate only if V4-B lands after mainnet or external-integration freeze. We are pre-both.
- Strategy C adds complexity with no clear payoff at this stage.

---

## 4. Discriminator handling for struct evolution

**The mechanic** (sources: https://medium.com/@jasonstanleyyoman/the-mystery-of-anchors-8-byte-discriminator-a-solana-developer-s-journey-da04e4b852ca, https://docs.rs/anchor-lang/latest/anchor_lang/trait.Discriminator.html, https://docs.huione.org/developers/anchor-book/anchor-bts/the-discriminator):

- An Anchor account's discriminator is the **first 8 bytes of `sha256("account:<StructName>")`**.
- On deserialize, Anchor checks those 8 bytes against the struct's expected discriminator; mismatch errors out *before* deserialization.
- **Renaming the struct changes the discriminator.** `Vault` and `Climb` have different discriminators even if their byte layout were identical.

**Pitfalls for V4-B:**

1. **Renaming `Vault` struct in-place** (if we ever tried Strategy B with a rename) would brick every existing on-chain `Vault` account because the new discriminator won't match.
2. **Reordering fields** doesn't change the discriminator (it's purely name-hash), but it changes byte layout — Borsh deserialize will succeed with garbage values, then your handler logic will misbehave silently. **Never reorder; only append.** Source: https://github.com/near/borsh (Borsh's self-describing guarantees are weak).
3. **Adding fields** doesn't change the discriminator either. Old on-chain accounts will then be *smaller than* the struct expects, causing deserialize failure. This is why realloc precedes field-add deploys. Source: https://solanacookbook.com/guides/data-migration.html
4. **Removing fields** in the middle of a struct shifts every subsequent field's byte offset — catastrophic. Only ever remove the *last* field and only after a realloc-shrink.

**Strategies for versioned accounts** (community consensus, not just one post):

- **Version byte** (`version: u8` as field 0 after discriminator): readers dispatch on it. Works for in-place migrations. Used by Metaplex Token Metadata and many AMMs. Source: https://solanacookbook.com/guides/data-migration.html
- **Fresh discriminator** (rename struct, e.g. `Vault` → `ClimbV2`): forces old accounts to be invalid, which is fine if you're doing Strategy A (fresh program) or a hard migration. Used by Squads v1→v4. Source: https://github.com/Squads-Protocol/v4
- **Anchor 0.31 custom discriminators** via `#[discriminator]`: lets you pin a chosen 8-byte value, enabling deliberate collision (e.g. new struct shape reading old discriminator) or deliberate separation. Source: https://github.com/solana-foundation/anchor/pull/2728 — **not available in this repo's 0.29 pin.**

**V4-B implication:** because we rename `Vault` → `Climb` + `Vault` (split), **the old `Vault` discriminator is naturally invalidated** on the new program ID. This aligns with Strategy A. If Strategy B were forced, we'd need the rename-in-place dance Squads demonstrated, which is gnarly.

---

## 5. Borsh serialization gotchas

Sources: https://github.com/near/borsh, https://extremelysunnyyk.medium.com/borsh-and-its-role-in-anchor-for-solana-48c19308328f, https://rareskills.io/post/solana-borsh-serialization, https://github.com/near/borsh/issues/99 (the long-standing `#[borsh_optional]` request).

**Core rule:** Borsh is **non-self-describing**. The byte layout is the schema. Any mismatch between the struct the writer used and the struct the reader uses produces either a deserialize error or silent garbage.

**Layout rules relevant to V4-B:**

1. **Fields serialize in declaration order.** No padding, no alignment, no length prefix except for dynamic types.
2. **`Option<T>` is a 1-byte tag (0x00 None, 0x01 Some) + inline T** (when Some). `Climb { vault: Option<Pubkey> }` per D1 adds 1 byte overhead + 32 when attached — not 33 always. Source: https://hexdocs.pm/borsh/Borsh.html
3. **`Vec<T>` is a 4-byte little-endian length prefix + inline items.** Resizing a `Vec` field implicitly resizes the account — Anchor does not auto-realloc for you.
4. **Nested structs inline.** `RecordBoardEntry` inside `Climb.record_board: [RecordBoardEntry; 10]` takes exactly 10 × sizeof(entry). No indirection.
5. **`String` is a Vec<u8> in Borsh terms.** 4-byte length + UTF-8 bytes. Fixed-width identifiers (like the existing `name: [u8; 64]` in `Vault`) are better: no length overhead, predictable size, no dynamic-size account math.

**The optional-field evolution constraint:**

- The **only safe-by-default** structural evolution in Borsh is **appending fields at the end** and **not reordering**.
- Even appending requires all existing accounts to be realloc'd or version-gated; otherwise reads will fail because the account is shorter than the struct expects.
- Removing: only from the tail, and only after account-population realloc-shrink.
- Inserting mid-struct: never safe. Always a silent data corruption.
- `#[borsh_optional]` has been requested since 2019 but is not merged. Source: https://github.com/near/borsh/issues/99

**Zero-copy accounts** (`#[account(zero_copy)]`) special considerations:

- Zero-copy uses `bytemuck::Pod`, requiring all fields to be `#[repr(C)]` and sized. Enums, `Vec`, `String`, `Option` all break it.
- Padding becomes visible: struct members pad to their alignment, and the padding bytes are part of the account layout. Add `_padding: [u8; N]` explicitly or you'll get a size mismatch.
- Source: https://github.com/solana-developers/anchor-zero-copy-example

V4-B uses Borsh (not zero-copy) for Climb/Vault based on existing idioms in `lib.rs`. That's the right call — splits with `Option<Pubkey>` and dynamic Record Board updates are hostile to zero-copy's `Pod` requirements.

**Common bug:** forgetting the discriminator in `SIZE` calc. Every `pub const SIZE` in this repo correctly starts with `8 // discriminator` — verify any new struct follows the idiom.

---

## 6. Upgrade authority patterns

Sources: https://solana.com/docs/programs/deploying, https://github.com/solana-labs/solana/issues/27932, https://github.com/solana-labs/solana/issues/21993, https://squads.xyz/blog/solana-multisig-program-upgrades-management, https://www.sec3.dev/blog/solana-internals-part-2-how-is-a-solana-program-deployed-and-upgraded, https://docs.solana.lido.fi/administration/, https://dev.to/compustable/the-solana-buffer-recovery-problem-nobody-talks-about-34cp

**The flow:**
- `solana program deploy` (or `anchor deploy`) writes bytecode to a **buffer account** then calls `BpfLoaderUpgradeable::DeployWithMaxDataLen`, promoting buffer → program data.
- The `upgrade-authority` is set to the deploying keypair by default.
- Subsequent upgrades: `solana program deploy --program-id <X> --upgrade-authority <K>` — the authority keypair `K` must sign.

**Buffer authority mismatch is the top source of deploy failures.** If the buffer authority ≠ program upgrade authority, the upgrade will fail. Source: https://github.com/solana-labs/solana/issues/21993. Mitigation: always explicitly pass `--buffer-authority` matching the upgrade authority on deploy, or use `solana program set-buffer-authority` before the swap.

**Freezing the upgrade authority** (making the program immutable): `solana program set-upgrade-authority <PROGRAM_ID> --final`. This is **irreversible**. Don't do it before mainnet. Source: https://www.quicknode.com/guides/solana-development/anchor/how-to-make-immutible-solana-programs

**Authority keypair lost?** If the upgrade authority keypair is lost, the program is effectively frozen. No recovery path. This is why production programs use multisig upgrade authorities. Sources: https://github.com/solana-labs/solana/issues/27932 (`set-upgrade-authority is scary`), https://medium.com/@snowflake_so/solana-multisig-program-upgrade-39d5273e509a

**Multisig upgrade authority patterns:**
- **Squads v4** is the modern default for solo-founder production. Source: https://squads.xyz/multisig
- **Serum Multisig** (used by Lido on Solana, 4/7 threshold) — the old-school pattern. Source: https://docs.solana.lido.fi/administration/
- **Goki/Tribeca** — used by Marinade historically.

**Buffer recovery:** if a deploy fails mid-way, you may have leftover buffer accounts holding 2+ SOL of rent. `solana program close <BUFFER_PUBKEY> --authority <K>` reclaims them. Source: https://dev.to/compustable/the-solana-buffer-recovery-problem-nobody-talks-about-34cp

**V4-B specific:** V4-A's upgrade authority is `~/.config/solana/id.json` per the memory index. This is a solo-dev pattern — fine for devnet, but should become multisig before mainnet. Not a V4-B blocker, but flag before any grant-milestone deploy.

---

## 7. Event emission in evolution

Sources: https://www.anchor-lang.com/docs/features/events, https://docs.rs/anchor-lang/latest/anchor_lang/macro.emit_cpi.html, https://github.com/coral-xyz/anchor/issues/2408, https://github.com/solana-foundation/anchor/pull/2438, https://rareskills.io/post/solana-logs-transaction-history

**Two event APIs in modern Anchor:**

1. **`emit!(EventName { ... })`** — writes event data as a base64-encoded log line. Fast, cheap, **but RPC providers routinely truncate logs.** Unreliable for indexers that must see every event.
2. **`emit_cpi!(EventName { ... })`** — emits events via a self-CPI whose instruction data carries the event payload. Lives in the transaction's inner-instructions array, which RPCs do not truncate. Requires an `#[event_cpi]` annotation on the `Accounts` struct and adds a compute cost for the self-CPI.

**For V4-B indexer reliability, prefer `emit_cpi!`** for any event the indexer must see (settlement events, staker allocations, Record Royalty payouts). The V4-A settlement flow emits events; audit whether those are `emit!` or `emit_cpi!` and upgrade any must-see events.

**Renaming events.** Anchor event names, like account names, determine the discriminator (`sha256("event:<EventName>")[0..8]`). Renaming the event *changes its discriminator*, meaning indexers listening for the old name will stop receiving it.

**Dual-emit pattern for transitions:**

```rust
// During transition:
emit!(VaultCompleted { ... });     // old event, keeps old indexers working
emit!(ClimbCompleted { ... });     // new event, for new indexers
// After transition window:
// Drop the old emit.
```

For V4-B's `VaultCompleted` → `ClimbCompleted` rename (per PROTOCOL_ALIGNMENT_FIX_PLAN line 508), dual-emit for one deploy cycle is the community-converged safe path. Given Strategy A (fresh program ID), the indexer is already fully rewiring — single-emit `ClimbCompleted` under the new program is fine.

**Indexer impact of event renames:** an indexer listening to the old program ID sees nothing new (program is unused). An indexer repointed to the new program ID must know the new discriminator. Backend WS-2a (IDL-driven decoding) handles this mechanically; hand-rolled discriminator tables don't.

---

## 8. CPI patterns

Sources: https://solana.com/docs/core/cpi, https://www.anchor-lang.com/docs/basics/cpi, https://www.asymmetric.re/blog-archived/invocation-security-navigating-vulnerabilities-in-solana-cpis

**Signer seeds for PDAs in CPIs:**

```rust
let seeds = &[VAULT_SEED, &id.to_le_bytes(), &[bump]];
let signer_seeds = &[&seeds[..]];
token::transfer(
    CpiContext::new_with_signer(
        ctx.accounts.token_program.to_account_info(),
        Transfer { ... },
        signer_seeds,
    ),
    amount,
)?;
```

The bump must be stored in the PDA (`Vault.bump`) at init time and re-used on every CPI. Computing `find_program_address` on every CPI is wasteful; the stored bump saves ~1,500 compute units per CPI.

**Account passing conventions:**
- Accounts passed to a CPI must be a subset of those passed to the calling instruction (Solana's PDA-safety rule).
- The called program receives them in the order declared on its own `Accounts` struct.
- **Writable/signer flags propagate but do not escalate.** A non-signer at the top ix cannot become a signer mid-CPI unless the caller is a PDA that can `invoke_signed` for it. Source: https://github.com/solana-labs/solana/issues/14522

**CPI depth limit:** 4. A top-level ix can CPI into a program that CPI's into another, up to 4 levels deep. Exceeding this fails with `MaxSeedLengthExceeded`-style errors that are confusingly named. Source: https://solana.com/docs/core/cpi

**Arbitrary CPI vulnerability.** If a program accepts a target program ID as an account and CPI's into it without validating, an attacker passes a malicious clone that returns success without the intended state change. Fix: pin the target program ID in a constraint. Source: https://github.com/coral-xyz/sealevel-attacks/tree/master/programs/5-arbitrary-cpi

**Account reloading after CPI** — **open Anchor security issue (August 2025):**
- After a CPI mutates an account, Anchor's `account.reload()` refreshes data but **does not re-check program ownership.** A malicious CPI can swap the account's owner, and `reload()` will happily deserialize it as the wrong program's account.
- Source: https://github.com/solana-foundation/anchor/issues/3830
- **V4-B implication:** if any instruction CPI's into the SPL Token program (CAL/DUNG mint/transfer) and then reads back the TokenAccount, audit that the reload pattern is followed with a manual owner-check. Mostly theoretical but real.

---

## 9. Security patterns and known CVEs

Sources: https://www.helius.dev/blog/a-hitchhikers-guide-to-solana-program-security, https://github.com/coral-xyz/sealevel-attacks, https://github.com/sannykim/solsec, https://dev.to/ohmygod/solana-program-security-checklist-14-critical-checks-before-you-deploy-to-mainnet-2d66, https://github.com/Ackee-Blockchain/solana-common-attack-vectors

**Known Anchor 0.29 bugs to be aware of:**

- **Anchor issue #3830** (Aug 2025, unresolved at time of writing) — `account.reload()` does not verify program ownership, enabling a theoretical account-swap exploit after an arbitrary CPI. Mitigation: manual `require_keys_eq!(account.to_account_info().owner, expected_program_id)` after reload.
- **Anchor issue #3044** — tracks Solana 2.0 / Agave breakage across Anchor versions. Pinning to 0.29 + Solana 1.18 avoids the fallout.
- No published CVE specific to Anchor 0.29.0 as of Apr 2026 search. The GitHub advisory DB returns no Anchor-specific entries.

**Top Sealevel attack classes relevant to V4-B** (annotated list from https://github.com/coral-xyz/sealevel-attacks):

1. **Missing signer check** — covered by Anchor `Signer<'info>`. Audit: the V3 security hardening commit (`1d113eac`) added `backend_authority` gates. V4-B must preserve these on every `Climb` + `Vault` mutation ix.
2. **Missing owner check** — covered by Anchor `Account<'info, T>` (checks `owner == program_id`). Raw `AccountInfo` does not. Audit any `CHECK:` comments.
3. **Arbitrary CPI** — covered by pinning program IDs in constraints (e.g. `program = token_program, token::mint = mint`).
4. **Type cosplay** — deserializing account X as type Y. Covered by the discriminator. Still a risk if using raw `AccountInfo`.
5. **Duplicate mutable accounts** — two accounts in the ix pointing to the same on-chain account. Covered by Anchor's `has_one`/`constraint = a.key() != b.key()`.
6. **Re-initialization** — covered by `init` (not `init-if-needed`). This repo opts into `init-if-needed` globally — audit each usage. Sources: https://rareskills.io/post/init-if-needed-anchor, https://solana.com/developers/courses/program-security/reinitialization-attacks
7. **PDA seed collision** — two different account types with overlapping seed structures. V4-B adds `RIDE_ATTESTATION_SEED`, `CAL_MINT_RECEIPT_SEED`, `CLIMB_COMPLETION_RECEIPT_SEED`. Audit that no two seeds + their key-space can collide.
8. **Integer overflow** — mitigated by `overflow-checks = true` in release profile (this repo has it, `Cargo.toml:8`). Still audit any raw `a + b` on u64 balances near supply caps.
9. **Closing account** (account closing with lamports attack) — draining lamports to 0 leaves data readable from ledger history; the proper close requires `close = <recipient>`. Audit any `close_` instructions.

**Account reloading vulnerability** (https://deepwiki.com/dreamerinsgp/solana-common-attack-vectors/8-account-reloading-vulnerability) — after a CPI mutates a token account balance, forgetting to `reload()` makes on-chain invariant checks stale. V4-B's finalization flow transfers CAL/DUNG across many accounts per ix; every post-transfer read must be a reload-then-check.

**Deployment security checklist** (synthesized from Helius Hitchhiker's Guide and DEV 14-check checklist):

1. Every ix has explicit signer requirements.
2. Every `Account<'info, T>` has implicit owner check; every `AccountInfo` has manual owner check.
3. Every PDA has explicit bump storage and seeds validation.
4. All math uses checked arithmetic or overflow-checks enabled.
5. `init-if-needed` usages have manual idempotency checks.
6. No arbitrary CPI — target program IDs pinned.
7. Account close paths use `close = <recipient>`.
8. Reloads after CPI include owner recheck until Anchor 0.x fixes #3830.
9. Rent-exempt invariant preserved across realloc.
10. Discriminator checks: never use raw `AccountInfo` for typed reads.
11. Fuzz tests for arithmetic edges (underflow on pending_rewards, overflow near supply cap).
12. Explicit tests for missing-signer, duplicate-account, arbitrary-CPI attack surfaces.

---

## 10. Anchor test framework gotchas

Sources: https://www.quicknode.com/guides/solana-development/legacy/bankrun, https://solana.com/developers/guides/advanced/testing-with-jest-and-bankrun, https://www.helius.dev/blog/a-guide-to-testing-solana-programs, https://kevinheavey.github.io/solana-bankrun/tutorial/, https://www.anchor-lang.com/docs/testing/litesvm

**How `anchor test` bootstraps localnet:**
- Spins up `solana-test-validator` with the program's `.so` deployed.
- Runs the TS/JS test suite against it.
- Validator has fresh state every test run (`--reset` by default).

**Common failures the community has converged on:**

1. **Stale `.so`.** If you edit Rust but don't re-run `anchor build`, tests run against old bytecode. Fix: always `anchor build && anchor test`, or use `anchor test --skip-build` only when intentional.
2. **Keypair confusion.** The wallet path in `Anchor.toml` must exist and be funded on the local validator. Localnet starts with the wallet funded; devnet tests require manual airdrops.
3. **IDL staleness.** If the IDL in `target/idl/` is from a previous build, the TS client deserializes to the wrong shape silently. Fix: `anchor build` rebuilds it.
4. **Compute budget** — default 200K CU may not be enough for finalization loops over many stakers. Use `ComputeBudgetProgram.setComputeUnitLimit(1_000_000)` in TS.
5. **Program ID collision** — if `declare_id!` in source differs from `[programs.localnet]` in `Anchor.toml`, tests fail obscurely. These must match, and the keypair at `target/deploy/<name>-keypair.json` must derive to the same ID.

**Bankrun / LiteSVM** — 10x faster than `solana-test-validator`:
- Bankrun: `start_anchor(path_to_project)` auto-loads the workspace's programs. Supports `context.set_clock({ unix_timestamp: ... })` for deterministic time-dependent tests. Source: https://kevinheavey.github.io/solana-bankrun/tutorial/
- LiteSVM: newer, Anchor-recommended. https://www.anchor-lang.com/docs/testing/litesvm

**Mocking on-chain clock.** `Clock` sysvar is a per-slot syscall; `solana-test-validator` advances it in real time. To test epoch boundaries, either:
- Use Bankrun's `set_clock()` to jump forward.
- Parameterize your code to take `unix_timestamp: i64` from the instruction (V4-A already does this for `finalize_settlement_week` via the `timestamp` parameter).

**Snapshot / golden-fixture patterns.** The community idiom is to write a `.ts` test that builds the full state (vault + stakes + ride attestations + finalization), then assert on every balance and PDA field. A "golden" test file of post-settlement state is the clearest regression net. V4-A's `scripts/smoke_settlement_projection.ts` (implied by commit `a672558b Add V4-A settlement projections and smoke helper`) is this pattern.

---

## 11. Climb/Vault split — established reference patterns

The V4-B split is a specific case of "**separate identity from state**" — an established pattern in the Solana ecosystem, though the naming varies.

**Metaplex Token Metadata + Master Edition** (canonical reference):
- `Metadata` account: permanent identity for an NFT — name, symbol, uri, creators, collection.
- `MasterEdition` account: economic state — print supply, supply cap, non-fungibility proof.
- **Separate PDAs**, both derived from the mint, both owned by the Token Metadata program.
- The split lets you update metadata (identity fields) without touching edition state, and vice versa.
- Source: https://developers.metaplex.com/token-metadata, https://lorisleiva.com/owning-digital-assets-in-solana/how-nfts-are-represented-in-solana

**Lesson for V4-B:** `Climb` ≈ `Metadata` (permanent identity, Record Board, founder, KOM); `Vault` ≈ `MasterEdition` (economic state, staking, carries, settlement). The correspondence is striking. Let the Metaplex split guide the Anchor idiom: both PDAs derive from a shared seed (e.g. `canonical_signature_hash`), and the Vault account stores `climb: Pubkey` explicitly.

**Squads v4 multisig + proposal separation:**
- `Multisig` account: membership, threshold, config.
- `Proposal` account: per-proposal state (votes, execution status).
- Many proposals per multisig. Lifecycle separation.
- Source: https://github.com/Squads-Protocol/v4, https://docs.squads.so/main/development/typescript/accounts/multisig
- **Lesson for V4-B:** **one-to-many vs one-to-one matters.** Climb:Vault is 1:1 per PROTOCOL_TRUTHS §2.2. Squads' lifecycle patterns (Proposal lifecycle — Active/Executed/Cancelled) map loosely onto Vault settlement-week state but that's a reach; the stronger takeaway is that they keep per-lifecycle state on the *state* account not the *identity* account.

**Marinade (mSOL) separation of stake accounts from staker state:**
- Stake accounts: native Solana stake, one per validator delegation.
- `State` account: Marinade's global economic state.
- `TicketAccount`: per-user unstake request.
- Source: Marinade's on-chain code is at https://github.com/marinade-finance — docs at https://marinade.finance/blog/marinade-vs-jito
- **Lesson for V4-B:** Marinade keeps per-user state in its own account type. `VaultStake` (per-user) + `Vault` (per-climb) already follow this; V4-B preserves it.

**The canonical pattern name:** "NFT-metadata pattern" or "identity-state split." The community doesn't have a universally agreed name, but the shape is consistent across these four references.

---

## 12. Realloc-with-split specific pattern

**Splitting one account into two is harder than growing one.** You can't realloc one account into two; realloc only changes a single account's size. You must:

1. **Create the new account(s) in a migration instruction.** For each existing `Vault`, run `migrate_vault_to_climb_and_vault(old_vault)` which:
   - Reads `old_vault.signature`, `.minter`, `.name`, etc.
   - `init`s a new `Climb` PDA at `[CLIMB_SEED, signature_hash]` with the identity fields.
   - `init`s a new `Vault` PDA at `[VAULT_SEED, climb.key().as_ref()]` with the economic fields, setting `vault.climb = climb.key()`.
   - Closes the old `Vault` PDA (transfers lamports to the migration payer).
2. **This is not a realloc — it's a reparent.** Old data is gone; new data is fresh.

**Cost:**
- **Rent:** 2 new accounts × (128-byte overhead + struct size) — roughly doubles rent cost per vault. For N=1000 climbs this is ~5-10 SOL on mainnet pricing.
- **Compute:** two inits + one close = ~15K CU per migration.
- **Complexity:** you need a batch migration script with retry logic and idempotency (re-running against already-migrated vaults must no-op).

**Community consensus:** **fresh deployment (Strategy A) is canonically preferred over in-place realloc-with-split** precisely because split is a reparent, not a resize. Sources: https://solanacookbook.com/guides/data-migration.html implicitly recommends fresh-deploy for non-additive changes; https://github.com/Squads-Protocol/v4 did a fresh redeploy for their much-larger shape change.

**V4-B specific cost-benefit:**
- **Strategy A (fresh program):** reseeds ~0 climbs (devnet test state is ephemeral, reseedable from the indexed DB). Zero migration complexity.
- **Strategy B (in-place realloc-with-split):** requires migration ix, batch script, idempotency logic, rollback plan. Only worthwhile if we can't afford to lose devnet state — **which we can.**
- **Decision:** sibling research will formalize, but Strategy A is the obvious winner.

---

## 13. Deployment checklist distilled from community practice

Merged from https://dev.to/ohmygod/solana-program-security-checklist-14-critical-checks-before-you-deploy-to-mainnet-2d66, https://www.helius.dev/blog/a-hitchhikers-guide-to-solana-program-security, https://squads.xyz/blog/solana-multisig-program-upgrades-management, https://solana.com/docs/programs/deploying.

### Pre-deploy

- [ ] Anchor + Solana CLI versions pinned and documented in `Anchor.toml` and `Cargo.toml`.
- [ ] `anchor build` clean; no warnings on the build target.
- [ ] All tests passing locally and in CI (Bankrun + Anchor test suite).
- [ ] Fuzz tests for arithmetic at boundaries (u64 overflow near supply cap, underflow on pending_rewards).
- [ ] Program size check (`anchor verify` or `solana program dump`): fits in 2x current deploy slot.
- [ ] `declare_id!` matches `Anchor.toml [programs.<cluster>]` matches on-chain program ID.

### Authority handling

- [ ] Upgrade authority is the intended keypair (ideally multisig for mainnet).
- [ ] Buffer authority = upgrade authority (avoid issue #21993).
- [ ] If using multisig (Squads/Serum), tx-builder rehearsed on devnet first.

### Rollback plan

- [ ] Previous `.so` archived off-chain with git tag.
- [ ] For Strategy A migrations: old program ID retained as fallback for clients until new program is validated.
- [ ] For Strategy B migrations: version byte check in code means unknown-version accounts fail deserialize rather than crash.

### Monitoring

- [ ] Indexer repointed or multi-program-aware.
- [ ] Metrics on: first successful instruction call, first completion, first settlement — set alerts.
- [ ] Log sink captures program errors and CPI failures for first 24h post-deploy.

### Communication

- [ ] Announcement docs updated (for this repo: `docs/CAL_ALLOCATION_PIPELINE_ANNOUNCEMENT.md` equivalent).
- [ ] `addresses.devnet.json` updated with new program ID; stale addresses grepped per `devnet-address-guard` hook.
- [ ] Any client SDKs republished with the new IDL.

---

## 14. Pitfalls specifically relevant to V4-B

Combining the above, the top gotchas the protocol agent (or a stand-in) will hit:

1. **Reparent, not realloc.** Splitting `Vault` into `Climb` + `Vault` is a *reparent* — you can't realloc one account into two. Plan for 2 new inits + 1 old close per migrated vault, not a single realloc. (§12)

2. **Discriminator of the new `Vault` is not the old `Vault`.** Even though the name is kept, decomposing the struct's fields changes byte layout but not the discriminator (name-hash only). **On the new program ID (Strategy A), the old `Vault` discriminator's on-chain accounts are inert — good.** If you ever tried Strategy B with a rename + in-place migration, you'd need to read the old discriminator first, write the new one last; the Anchor macro won't do this for you. (§4, §12)

3. **Backend IDL staleness.** V4-A's redeploy already required WS-2a to kill hand-written decoders and go IDL-driven. V4-B will invalidate those decoders again. Anchor 0.29's IDL is the pre-0.30 format — backend decoders must handle that specific format, not the 0.30+ one. (§1)

4. **`init-if-needed` is on across this repo** (`Cargo.toml:16`). Any V4-B ix that takes shortcut via `init-if-needed` for new Climb or Vault accounts **must include explicit idempotency checks** — re-running the founding ix on an already-founded Climb must no-op or error, not reset. The reinitialization attack surface is real. (§2, §9)

5. **`account.reload()` owner check bug (Anchor #3830, Aug 2025, unresolved).** V4-B finalization flows will CPI into SPL Token for DUNG mint/transfer and read back token account balances. Every post-CPI reload must manually verify `account.owner == token_program::ID` until Anchor patches this. Add a `require_keys_eq!` guard. (§8, §9)

6. **PDA seed collision surface grows with V4-B.** New seeds: `RIDE_ATTESTATION_SEED`, `CLIMB_COMPLETION_RECEIPT_SEED`, `CAL_MINT_RECEIPT_SEED`, plus the existing `VAULT_SEED`. Audit that no seed + its key-space overlaps another (e.g. `[VAULT_SEED, id_bytes]` cannot collide with `[CLIMB_SEED, signature_hash]` — different lengths, but always double-check). (§9)

7. **`emit!` events for settlement are unreliable for indexers.** V4-B's finalization emits one event per staker allocation + one per Record Royalty payout — that's 10-20 events per vault per settlement week. If any of those use `emit!` and go through a high-traffic RPC that truncates logs, the indexer silently misses payouts. **Use `emit_cpi!`** for all settlement-critical events. (§7)

8. **Test-clock manipulation required.** V4-B's finalization depends on epoch boundaries. `solana-test-validator` advances clock in real time; tests that verify "8 epochs later the Local Legend term expires" cannot run in real time. Migrate any such tests to Bankrun with `context.set_clock()`. (§10)

9. **Compute budget on finalization loops.** V4-A already iterates eligible stakers in `finalize_settlement_week`. V4-B preserves this. A 50+ staker vault can exceed the 200K default CU budget. Set a 1M CU limit via `ComputeBudgetProgram.setComputeUnitLimit` in the backend tx-builder, or batch settlement in chunks. (§10)

10. **Solana overflow-checks release profile.** This repo sets `overflow-checks = true` in `Cargo.toml:8`. V4-B adds new arithmetic paths (Record Royalty rank-percentage math, multi-bucket carry summation). If any `u64 * u64` exceeds `u64::MAX` even transiently, the program panics instead of wrapping. Prefer `u128` intermediates for bucket-share computations. Pattern: `(bucket_amount as u128 * pct_bps as u128 / 10_000) as u64`. (§5, §9)

---

## 15. Reading list

**Anchor release notes:**
- Anchor 0.29.0 — https://www.anchor-lang.com/docs/updates/release-notes/0-29-0
- Anchor 0.30.0 — https://www.anchor-lang.com/docs/updates/release-notes/0-30-0
- Anchor 0.30.1 — https://www.anchor-lang.com/docs/updates/release-notes/0-30-1
- Anchor 0.31.0 — https://www.anchor-lang.com/docs/updates/release-notes/0-31-0
- Anchor CHANGELOG master — https://github.com/solana-foundation/anchor/blob/master/CHANGELOG.md

**Anchor core docs:**
- Program structure — https://www.anchor-lang.com/docs/basics/program-structure
- The Accounts Struct — https://www.anchor-lang.com/docs/the-accounts-struct
- Account Constraints — https://www.anchor-lang.com/docs/references/account-constraints
- CPI — https://www.anchor-lang.com/docs/basics/cpi
- Events — https://www.anchor-lang.com/docs/features/events
- IDL — https://www.anchor-lang.com/docs/basics/idl
- LiteSVM testing — https://www.anchor-lang.com/docs/testing/litesvm

**Realloc + rent:**
- RareSkills — Cost of storage, maximum storage size, and account resizing in Solana — https://rareskills.io/post/solana-account-rent
- DEV — How to change account size on Solana — https://dev.to/jacobcreech/how-to-change-account-size-on-solana-55b4
- Solana Cookbook — Program Accounts Data Migration — https://solanacookbook.com/guides/data-migration.html
- Anchor realloc test — https://github.com/solana-foundation/anchor/blob/master/tests/realloc/tests/realloc.ts
- Solana issue #14694 — BPF programs have limited ability to realloc — https://github.com/solana-labs/solana/issues/14694

**Discriminators + Borsh:**
- Mystery of Anchor's 8-Byte Discriminator — https://medium.com/@jasonstanleyyoman/the-mystery-of-anchors-8-byte-discriminator-a-solana-developer-s-journey-da04e4b852ca
- Custom discriminators issue — https://github.com/coral-xyz/anchor/issues/3097
- #[interface] attribute PR — https://github.com/solana-foundation/anchor/pull/2728
- Borsh GitHub — https://github.com/near/borsh
- `#[borsh_optional]` request — https://github.com/near/borsh/issues/99
- Borsh and its role in Anchor — https://extremelysunnyyk.medium.com/borsh-and-its-role-in-anchor-for-solana-48c19308328f
- RareSkills Borsh Serialization — https://rareskills.io/post/solana-borsh-serialization

**Upgrade authority + deployment:**
- Solana Deploying Programs — https://solana.com/docs/programs/deploying
- Solana Program Deployment — https://solana.com/docs/core/programs/program-deployment
- Sec3 — Solana Internals Part 2 — https://www.sec3.dev/blog/solana-internals-part-2-how-is-a-solana-program-deployed-and-upgraded
- set-upgrade-authority is scary (issue #27932) — https://github.com/solana-labs/solana/issues/27932
- Use program upgrade authority for buffer authority (#21993) — https://github.com/solana-labs/solana/issues/21993
- Squads — Managing Program Upgrades with Multisig — https://squads.xyz/blog/solana-multisig-program-upgrades-management
- Snowflake — Solana Multisig Program Upgrade — https://medium.com/@snowflake_so/solana-multisig-program-upgrade-39d5273e509a
- Solana Buffer Recovery — https://dev.to/compustable/the-solana-buffer-recovery-problem-nobody-talks-about-34cp
- Lido Administration — https://docs.solana.lido.fi/administration/
- How to Make an Immutable Solana Program — https://www.quicknode.com/guides/solana-development/anchor/how-to-make-immutible-solana-programs

**CPI + security:**
- Solana CPI docs — https://solana.com/docs/core/cpi
- Asymmetric Research — Invocation Security — https://www.asymmetric.re/blog-archived/invocation-security-navigating-vulnerabilities-in-solana-cpis
- Helius — Hitchhiker's Guide to Solana Program Security — https://www.helius.dev/blog/a-hitchhikers-guide-to-solana-program-security
- Sealevel Attacks — https://github.com/coral-xyz/sealevel-attacks
- Arbitrary CPI example — https://github.com/coral-xyz/sealevel-attacks/tree/master/programs/5-arbitrary-cpi
- solsec collection — https://github.com/sannykim/solsec
- Solana Common Attack Vectors — https://github.com/Ackee-Blockchain/solana-common-attack-vectors
- Solana Program Security Checklist (14 checks) — https://dev.to/ohmygod/solana-program-security-checklist-14-critical-checks-before-you-deploy-to-mainnet-2d66
- Anchor #3830 — account reload after CPI doesn't check program ownership — https://github.com/solana-foundation/anchor/issues/3830
- Anchor #3044 — Solana 2.0 breakage — https://github.com/solana-foundation/anchor/issues/3044
- RareSkills — init_if_needed and the reinitialization attack — https://rareskills.io/post/init-if-needed-anchor
- Solana developer content — Reinitialization Attacks — https://solana.com/developers/courses/program-security/reinitialization-attacks
- Difficult to debug CPI privilege escalation errors (#14522) — https://github.com/solana-labs/solana/issues/14522
- Account Reloading Vulnerability — https://deepwiki.com/dreamerinsgp/solana-common-attack-vectors/8-account-reloading-vulnerability

**Events:**
- Anchor new event API discussion (#2408) — https://github.com/coral-xyz/anchor/issues/2408
- Feature: CPI Events API (PR #2438) — https://github.com/solana-foundation/anchor/pull/2438
- RareSkills — Solana logs, events, and transaction history — https://rareskills.io/post/solana-logs-transaction-history
- `emit_cpi` macro docs — https://docs.rs/anchor-lang/latest/anchor_lang/macro.emit_cpi.html

**Testing:**
- Bankrun guide (Quicknode) — https://www.quicknode.com/guides/solana-development/legacy/bankrun
- Bankrun tutorial — https://kevinheavey.github.io/solana-bankrun/tutorial/
- Helius — A Guide to Testing Solana Programs — https://www.helius.dev/blog/a-guide-to-testing-solana-programs
- Solana Foundation — Testing with Jest and Bankrun — https://solana.com/developers/guides/advanced/testing-with-jest-and-bankrun
- Anchor zero-copy example — https://github.com/solana-developers/anchor-zero-copy-example

**Agave / version migration:**
- Agave v2.0 Transition Guide — https://github.com/anza-xyz/agave/wiki/Agave-v2.0-Transition-Guide
- Helius — Agave v2.0 Update — https://www.helius.dev/blog/agave-v2-update
- Helius — Solana v1.18 Update — https://www.helius.dev/blog/all-you-need-to-know-about-solanas-v1-18-update

**Migration case studies (Metaplex, Squads, Marinade, Jito):**
- Metaplex Token Metadata overview — https://developers.metaplex.com/token-metadata
- How NFTs are represented in Solana (Loris Leiva) — https://lorisleiva.com/owning-digital-assets-in-solana/how-nfts-are-represented-in-solana
- Sec3 — Solana programs Part 3: Metaplex Token Metadata — https://www.sec3.dev/blog/solana-programs-part-3
- Squads v4 — https://github.com/Squads-Protocol/v4
- Squads Multisig docs — https://docs.squads.so/main
- Squads account structure — https://docs.squads.so/main/development/typescript/accounts/multisig
- The Struggle of Integrating Jito Staking Vault — https://medium.com/@chajesse/the-struggle-of-integrating-jito-staking-vault-into-my-solana-program-3195b5b3c7a5
- Marinade vs Jito — https://marinade.finance/blog/marinade-vs-jito

**IDL:**
- Anchor Solana Program IDL (RareSkills) — https://rareskills.io/post/anchor-idl
- Anchor IDL and managing older versions — https://blog.chalda.cz/posts/anchor-idl/
- Reading Another Anchor Program's Account Data (RareSkills) — https://rareskills.io/post/anchor-read-account

---

**End of reference.** If anything here contradicts `docs/PROTOCOL_TRUTHS.md` or `docs/design/PROTOCOL_ALIGNMENT_FIX_PLAN.md`, those win. This doc is working knowledge, not policy.
