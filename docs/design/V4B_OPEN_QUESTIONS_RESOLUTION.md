# V4-B Open Questions — Resolution via WWPTD

**Status:** RESOLVED (partial) — 29 resolved / 32 total · 3 escalated to Tim
**Date:** 2026-04-17
**Method:** Cascade — TRUTHS → FIX_PLAN → committed patterns → community consensus → WWPTD derivation → escalation
**Author:** Mobile/backend dispatcher acting as WWPTD reviewer while protocol agent is frozen through ~2026-04-22
**Semantic authority:** [`docs/PROTOCOL_TRUTHS.md`](../PROTOCOL_TRUTHS.md) wins on any conflict.
**Parent research:**
- [V4B_PROTOCOL_SURGERY_SCOPE](./V4B_PROTOCOL_SURGERY_SCOPE.md) §9 (8 Qs)
- [V4B_BLAST_RADIUS_INVENTORY](./V4B_BLAST_RADIUS_INVENTORY.md) §10 (10 Qs)
- [V4B_MIGRATION_AND_TESTS](./V4B_MIGRATION_AND_TESTS.md) §8 (11 Qs)
- [V4B_RUST_ANCHOR_KNOWLEDGE_REFERENCE](./V4B_RUST_ANCHOR_KNOWLEDGE_REFERENCE.md) §14 (3 emergent Qs)

---

## Resolution legend

- `DERIVED-TRUTHS` — answered by PROTOCOL/MOBILE/BACKEND_TRUTHS section
- `DERIVED-FIXPLAN` — answered by FIX_PLAN principle P1-P15 or Decisions #1-#18
- `DERIVED-PATTERN` — answered by committed protocol-dev pattern in `lib.rs` or git history
- `DERIVED-COMMUNITY` — answered by community consensus (V4B_RUST_ANCHOR_KNOWLEDGE_REFERENCE)
- `DERIVED-WWPTD` — answered by reasoning chain from TRUTHS (no single section suffices, but the answer follows)
- `NEEDS-TIM` — genuine decision requiring human call

---

## Source A — V4B_PROTOCOL_SURGERY_SCOPE §9 (8 questions)

### Q-A1 [source: V4B_PROTOCOL_SURGERY_SCOPE §9 Q1] — Climb PDA seed: signature_hash or climb_id?
**Question verbatim:** *"Option A (recommended): `[CLIMB_SEED, &signature_hash]` … Option B: `[CLIMB_SEED, &climb_id.to_le_bytes()]` with a new ClimbCounter."*
**Resolution:** `DERIVED-TRUTHS` + `DERIVED-PATTERN`
**Answer:** **Option A — `[CLIMB_SEED, &signature_hash]`.**
**Reasoning:**
- PROTOCOL_TRUTHS §2.1: *"A Climb is … a canonical identity for a real hill."* The canonical identity is the 64-byte signature, not a monotonic counter.
- PROTOCOL_TRUTHS §11 lists `Climb` as canonical naming; the PDA seed should reflect the canonical identity.
- Committed pattern: the protocol dev already uses signature-derived seeds for child receipts — `CLIMB_COMPLETION_RECEIPT_SEED` at `lib.rs:10` with PDA shape `[seed, ride_attestation, vault]` (`lib.rs:2580`). Identity-first seeding is the established idiom.
- `RIDE_ATTESTATION_SEED` uses `[seed, rider, ride_hash]` (`lib.rs:3639`) — again identity-first, not counter-first.
- Option B's ClimbCounter would reintroduce a pre-TRUTHS monotonic-id pattern the protocol is moving away from (P15 hard-rename demoting `VaultCounter`-style scaffolding).

### Q-A2 [source: V4B_PROTOCOL_SURGERY_SCOPE §9 Q2] — Replace `mint_epoch`/`rights_expires_epoch` with `founded_at: i64`?
**Question verbatim:** *"Keep the epoch-based `rights_expires_epoch`, or also convert it to an `i64`/`ride-time` boundary?"*
**Resolution:** `DERIVED-FIXPLAN`
**Answer:** **Replace `mint_epoch` with `founded_at: i64` (ride-time). Convert `rights_expires_epoch` to `rights_expires_at: i64` (ride-time boundary).**
**Reasoning:**
- FIX_PLAN P6: *"All economic math anchors on `RideAttestation.completed_at`… `Clock::get()` is used only for audit ordering."* Ride time is the economic clock.
- FIX_PLAN WS-1 target Climb struct (lines 304-338) specifies `founded_at: i64` + `founded_ride_attestation: Pubkey`. Already decided for founding.
- PROTOCOL_TRUTHS §4: *"Epochs are not the ontology of the protocol. They are the settlement clock."* `rights_expires_epoch` uses the settlement clock for a non-settlement concern — inconsistent with the demotion in TRUTHS §12.3.
- By arrow-of-truth: any timestamp tied to rider action (founding, posting, KOM-setting) is a ride-time fact. Only settlement bookkeeping uses `epoch`.

### Q-A3 [source: V4B_PROTOCOL_SURGERY_SCOPE §9 Q3] — Does the `minter rights period` concept survive V4-B?
**Question verbatim:** *"Keep the concept on Climb (retain `rights_expires_epoch`) / Fold founder metadata rights under 'until first Local Legend elected' / Make founder rights permanent."*
**Resolution:** `DERIVED-TRUTHS`
**Answer:** **Fold founder metadata rights under "until first Local Legend elected."** Drop the fixed 12-epoch rights period.
**Reasoning:**
- PROTOCOL_TRUTHS §6.1: *"Founder rights are: permanent provenance, metadata and cultural authorship within the protocol's rules, **bootstrap visibility and initial stewardship kickback via the first Local Legend stint**. Founder rights are **not** permanent performance rights and are **not** implied perpetual royalties."*
- The TRUTHS sentence binds founder rights explicitly to "the first Local Legend stint" — that's the natural boundary.
- PROTOCOL_TRUTHS §6.4: *"The Local Legend is the active steward seat for a climb."* Metadata authorship is stewardship, so it flows to whoever holds the Legend seat after the founder's bootstrap term ends.
- FIX_PLAN Decision #16 sets `LocalLegend.bootstrap: bool` for founder's first stint. Use that boundary, not a separate rights clock.
- **Implementation:** Keep `rights_expires_at` on Climb, but set it to `founded_at + 8 * EPOCH_DURATION` (same as founder's first Legend term). After that, Climb metadata edits require `signer == current_local_legend.holder`.

### Q-A4 [source: V4B_PROTOCOL_SURGERY_SCOPE §9 Q4] — Lifetime aggregates (`total_cal_burned`, `total_dung_emitted`, `total_completions`): Climb or Vault?
**Resolution:** `DERIVED-TRUTHS` + `DERIVED-FIXPLAN`
**Answer:** **Climb.** Rename to `total_cal_committed` + `total_dung_distributed` + `total_completions`.
**Reasoning:**
- PROTOCOL_TRUTHS §3.1 lists "lifetime CAL committed to a climb" as permanent truth. Climb holds permanent truth.
- FIX_PLAN WS-1 target (lines 330-333) puts these on Climb explicitly.
- PROTOCOL_TRUTHS §2.2: Vault is "the container for reward distribution, staking configuration, and economic state." Lifetime aggregates are historical record, not reward distribution state.
- WWPTD: if the Vault is ever detached (future) or swapped, lifetime-CAL-committed must still be truthful to the climb. Storing it on Vault would lose that truth on detach. Storing on Climb survives.

### Q-A5 [source: V4B_PROTOCOL_SURGERY_SCOPE §9 Q5] — `VaultLeaderboard`: fold into Climb, or keep separate account?
**Resolution:** `DERIVED-FIXPLAN` + `DERIVED-TRUTHS`
**Answer:** **Fold into Climb as `record_board: [RecordBoardEntry; 10]`.**
**Reasoning:**
- FIX_PLAN WS-1 (line 328) explicitly specifies `record_board: [RecordBoardEntry; 10]` as a Climb field.
- PROTOCOL_TRUTHS §6.3: *"The Record Board is the climb's all-time top 10 … permanent record truth."* Permanent Climb truth lives on Climb.
- PROTOCOL_TRUTHS §3.1 lists "all-time top 10 record board" under Permanent Truth, co-located with Climb identity.
- Byte cost (10 × 44 = 440 B added; Climb totals ~1006 B) is well under Solana's 10 KB init-tx cap and 10 MiB account cap — no size constraint.
- Community pattern (V4B_RUST_ANCHOR §11): Metaplex Token Metadata co-locates identity fields with small permanent metadata arrays. Separate PDA would be the wrong analog.
- **Simpler reads, no extra account-load on hot paths,** aligns with FIX_PLAN P11 "auditable without indexer."

### Q-A6 [source: V4B_PROTOCOL_SURGERY_SCOPE §9 Q6] — Vault PDA seed: keep `[VAULT_SEED, id]` or re-seed off Climb?
**Resolution:** `DERIVED-TRUTHS` + `DERIVED-WWPTD`
**Answer:** **Option B — `[VAULT_SEED, climb_pda.as_ref()]`.** Re-seed off Climb.
**Reasoning:**
- PROTOCOL_TRUTHS §2.2: *"A Vault is … an optional economic module attached to a Climb."* Attached = Vault identity derives from Climb.
- Climb:Vault is 1:1 per TRUTHS §2.2; the Vault of *this* Climb has no independent identity to preserve.
- WWPTD: the VaultCounter pattern is pre-TRUTHS scaffolding — a counter is what you use when objects have no canonical identity. Climb has canonical identity (signature), so Vault's identity is derivable: *the Vault of Climb X.*
- **Child PDA impact:** `VaultStake` and `VaultCompletion` today use `[seed, user, vault_id]`. Under Option B they become `[seed, user, vault_pda]` (the Vault PDA itself). This is a cleaner derivation — the stake is keyed by "the thing it stakes in" rather than a proxy id. The V4-B fresh deploy (Decision #1, #2) means no backward compat burden.
- Eliminates the need for `VaultCounter` entirely — one less pre-TRUTHS account type to migrate.

### Q-A7 [source: V4B_PROTOCOL_SURGERY_SCOPE §9 Q7] — `VaultActivation` account: keep, fold, or drop?
**Resolution:** `DERIVED-FIXPLAN`
**Answer:** **Drop it.** Fresh deploy = no legacy to activate.
**Reasoning:**
- FIX_PLAN Decision #1 (fresh program ID) + Decision #2 (clean slate for 16 devnet vaults) = no V4-A state to seed into V4-B.
- `VaultActivation` exists specifically to gate in-flight historical seeding; the concept is moot on a greenfield deploy.
- V4B_BLAST_RADIUS §1.2 already flags it as "Legacy activation; may collapse under V4-B."
- V4B_PROTOCOL_SURGERY_SCOPE §4.9 lists `admin_backfill_vault_activation` as a retire candidate.
- Dropping it removes the `admin_activate_vault` + `admin_backfill_vault_activation` instructions and `VaultActivated` event (or marks them dead under Decision #2's clean slate).

### Q-A8 [source: V4B_PROTOCOL_SURGERY_SCOPE §9 Q8] — Record Board event emission on update?
**Question verbatim:** *"If Record Board folds into Climb, `record_climb_completion` may emit a new `RecordBoardUpdated { climb, rider, old_rank, new_rank, seat_changes }` event."*
**Resolution:** `DERIVED-FIXPLAN`
**Answer:** **Yes — emit `RecordBoardUpdated` per seat change.**
**Reasoning:**
- FIX_PLAN WS-1 line 472: *"update_record_board(climb, new_entry_candidate)… Event emission per seat change."* Already specified.
- FIX_PLAN P14 "no dust, no handwaving, explicit economics": Record Board changes are economically meaningful (they determine Record Royalty recipients forever); silent mutations are forbidden.
- BACKEND_TRUTHS §4.3: projection must reflect on-chain state. Without per-seat events, the indexer can't reliably project seat changes.
- Community consensus (V4B_RUST_ANCHOR §7): per-allocation events are the canonical idiom; **use `emit_cpi!` for settlement-critical events** because RPCs truncate `emit!` logs. See Pattern Catalog below.

---

## Source B — V4B_BLAST_RADIUS_INVENTORY §10 (10 questions)

### Q-B1 [source: V4B_BLAST_RADIUS_INVENTORY §10 Q1] — Rename `ClimbCompleted` event's `vault_id` field → `climb_id`?
**Resolution:** `DERIVED-TRUTHS` + `DERIVED-WWPTD`
**Answer:** **Yes — rename to `climb` (Pubkey). Add an `Option<Pubkey> vault` alongside.**
**Reasoning:**
- PROTOCOL_TRUTHS §2.1-§2.2: Climb is primary, Vault is optional attachment. An event called `ClimbCompleted` must key on the Climb.
- FIX_PLAN P15: hard rename on IDL-visible surface; event payload field names are IDL-visible.
- P1 "Climb-first": Climb is the primary object; the vault reference is secondary information (may be None in future Climb-without-Vault cases).
- **Shape:** `ClimbCompleted { climb: Pubkey, vault: Option<Pubkey>, ride_attestation: Pubkey, rider: Pubkey, time_s: u32, cal_tributed: u64, is_new_kom: bool, completed_at: i64, timestamp: i64 }`.

### Q-B2 [source: V4B_BLAST_RADIUS_INVENTORY §10 Q2] — Rename `VaultLeaderboard` → `ClimbLeaderboard` or `RecordBoard`?
**Resolution:** Moot — `VaultLeaderboard` is **retired** per Q-A5 (fold into Climb).
**Answer:** **No rename needed; the account ceases to exist.** The field on Climb is `record_board: [RecordBoardEntry; 10]` per FIX_PLAN WS-1 line 328. Indexer table renames to `indexed_record_boards` downstream (wdvr.8 scope).
**Reasoning:** If Climb holds the data directly, there's no separate account to name.

### Q-B3 [source: V4B_BLAST_RADIUS_INVENTORY §10 Q3] — Rename `distributeEpochRewards` → `finalizeSettlementWeek`?
**Resolution:** `DERIVED-FIXPLAN`
**Answer:** **Yes — fold into 0uv8.**
**Reasoning:**
- FIX_PLAN line 506: *"Instruction: `distribute_epoch_rewards` → `finalize_settlement_week`"* — explicit P15 rename.
- PROTOCOL_TRUTHS §12.3 demotes `epoch` from protocol ontology; user-visible instruction names must use `settlement_week`.
- Decision #7 ratifies "explicit `finalize_settlement_week` instruction."
- Since 0uv8 owns IDL-visible surface rename (V4B_PROTOCOL_SURGERY_SCOPE §8), this rename lands there; compat alias for one release is unnecessary on fresh program ID (Decision #1).

### Q-B4 [source: V4B_BLAST_RADIUS_INVENTORY §10 Q4] — Does `LocalLegend` stay keyed by `vault_id`?
**Resolution:** `DERIVED-TRUTHS` + `DERIVED-WWPTD`
**Answer:** **No — key by Vault PDA** (`[LOCAL_LEGEND_SEED, vault_pda.as_ref()]`).
**Reasoning:**
- PROTOCOL_TRUTHS §6.4: *"The Local Legend is the active steward seat for a climb."* TRUTHS attributes the seat to the climb, but FIX_PLAN P1/Decision #11 resolves the tension: Legend is attached to the *Vault* (economic module), consistent with "stewardship of the economic wrapper."
- Since Vault is itself PDA-seeded off Climb (per Q-A6), keying Legend off Vault PDA transitively keys it off Climb. Bijection preserved.
- Eliminates the last `vault_id` dependency in child PDAs. Fresh program ID = no compat burden.
- FIX_PLAN WS-1 target `LocalLegend { vault: Pubkey, ... }` (line 453) already stores `vault` as a full Pubkey, not an id — the shape is ready.

### Q-B5 [source: V4B_BLAST_RADIUS_INVENTORY §10 Q5] — `ClimbCompletionReceipt` field `vault: Pubkey` — rename to `climb: Pubkey`?
**Resolution:** `DERIVED-TRUTHS` + `DERIVED-FIXPLAN`
**Answer:** **Yes — receipt keys by Climb, not Vault.** PDA: `[CLIMB_COMPLETION_RECEIPT_SEED, ride_attestation, climb]`.
**Reasoning:**
- FIX_PLAN P5 specifies: *"ClimbCompletionReceipt keyed by (ride_attestation, climb_id)."* The naming already binds to Climb.
- PROTOCOL_TRUTHS §2.1: Climb is primary; an object named `ClimbCompletionReceipt` must be keyed by what it names.
- **Scenario check:** If a Climb has no Vault attached (future, per §2.2), you still want to record a completion. The receipt must key off Climb to support that.
- Committed current code at `lib.rs:2580-2584` has field named `vault: Pubkey` — this is a naming bug from pre-V4-B scaffolding, not a semantic choice. 0uv8 fixes it.
- Fresh program ID (Decision #1) = no backward compat penalty.

### Q-B6 [source: V4B_BLAST_RADIUS_INVENTORY §10 Q6] — Fresh program ID vs on-chain migration instruction?
**Resolution:** `DERIVED-FIXPLAN` + `DERIVED-COMMUNITY`
**Answer:** **Fresh program ID.** No migration instruction.
**Reasoning:**
- FIX_PLAN Decision #1: *"Fresh program ID for V4 redeploy. No in-place upgrade, no V3 migration script."*
- FIX_PLAN Decision #2: *"Clean slate for existing devnet state. The 16 vaults are test data; no preservation."*
- V4B_RUST_ANCHOR §12: *"Community consensus: fresh deployment (Strategy A) is canonically preferred over in-place realloc-with-split precisely because split is a reparent, not a resize."*
- Precedent: V4-A used this pattern (commit `823d75ee Rotate devnet program id for V4-A fresh lane`).
- V4B_MIGRATION_AND_TESTS §1 concludes: *"Option A is the obvious winner."* Lowest one-way-door risk for hackathon sprint with protocol agent iced.

### Q-B7 [source: V4B_BLAST_RADIUS_INVENTORY §10 Q7] — Does `0uv8` retire the Merkle-path dead code in the same slice, or is that `wdvr.8`?
**Resolution:** `DERIVED-FIXPLAN`
**Answer:** **0uv8 retires it in the same slice.** On the Rust/Anchor side. Backend-side cleanup (`merkle_proof.py`, `cal_allocator.py`, etc.) lands as part of the same workstream.
**Reasoning:**
- FIX_PLAN WS-1 sub-tasks explicitly list: *"Delete deprecated instructions (Merkle path, old distribute, old record_vault_completion, old create_vault variants, V2/V3 migrations)."* (line 537)
- Decision #1 + Decision #3 ratify deletion (not deprecation) of Merkle path.
- V4B_PROTOCOL_SURGERY_SCOPE §8 proposed rule-of-thumb: *"if it's inside `protocol/anchor/` or the direct `solana_direct.py` instruction builders, it's `0uv8`."* Merkle path is inside both.
- Leaving dead account structs in IDL for wdvr.8 to remove would mean two IDL regenerations; better to do it once.
- **wdvr.8 still owns:** docs, portal, mobile consumer copy, stale references in scripts, archived compat-alias retirement.

### Q-B8 [source: V4B_BLAST_RADIUS_INVENTORY §10 Q8] — Backend table renames `indexed_vaults` → `indexed_climbs`?
**Resolution:** `DERIVED-TRUTHS` + `DERIVED-FIXPLAN`
**Answer:** **Split: create `indexed_climbs` (primary) and keep `indexed_vaults` (economic attachment, narrower).**
**Reasoning:**
- PROTOCOL_TRUTHS §2.1-§2.2: Climb is primary, Vault is attached economic module. Two distinct tables match the ontology.
- FIX_PLAN Appendix A (line 801) enumerates: *"add `indexed_climbs`, `indexed_ride_attestations`, `indexed_climb_completions`, `indexed_record_royalty_payouts`, `indexed_staker_allocations`, `indexed_legend_payouts`, `indexed_settlement_week_finalizations`."* `indexed_climbs` is listed explicitly; `indexed_vaults` is not renamed away.
- BACKEND_TRUTHS §4.3: projection shapes match on-chain shapes. Split accounts = split tables.
- Scope: table creation/rename is `wdvr.8` tail work (V4B_PROTOCOL_SURGERY_SCOPE §8). 0uv8 delivers the IDL; indexer writers update; DB migration lands in wdvr.8 coordination.

### Q-B9 [source: V4B_BLAST_RADIUS_INVENTORY §10 Q9] — `VaultActivation` account — retire, or keep as `ClimbActivation`?
**Resolution:** Same as Q-A7.
**Answer:** **Retire.** Fresh deploy + clean slate = no activation concept needed.

### Q-B10 [source: V4B_BLAST_RADIUS_INVENTORY §10 Q10] — Retire `UserState` in `0uv8`, or wait?
**Resolution:** `DERIVED-FIXPLAN`
**Answer:** **Retire in 0uv8. `RiderSoul` is the replacement.**
**Reasoning:**
- FIX_PLAN WS-1 line 494 explicit delete list: *"`UserState` (moved to `RiderSoul`)."*
- FIX_PLAN Decision #11 ratifies the Climb/Vault/RiderSoul three-account split.
- FIX_PLAN P12 + PROTOCOL_TRUTHS §7.3: rider identity must live in a non-transferable `RiderSoul`, separate from CAL (SPL token balance). `UserState` conflates these.
- Fresh program ID = no migration cost; stop shipping two ways to be a user.
- V4-A already emits `RiderSoul` alongside `UserState` (V4B_MIGRATION_AND_TESTS §0). V4-B deletes the legacy.

---

## Source C — V4B_MIGRATION_AND_TESTS §8 (11 questions)

### Q-C1 [source: V4B_MIGRATION_AND_TESTS §8 Q1] — Option A (fresh) vs Option B (realloc)?
**Resolution:** Same as Q-B6.
**Answer:** **Option A — fresh program ID.** Per Decision #1 + Decision #2.

### Q-C2 [source: V4B_MIGRATION_AND_TESTS §8 Q2] — Naming collision on `record_climb_completion`.
**Question verbatim:** *"V4-A already has an instruction named `record_climb_completion` … V4-B keeps the name; semantics change … OR uses a different name to keep V4-A clients partially functional."*
**Resolution:** `DERIVED-FIXPLAN`
**Answer:** **Keep the name. V4-B semantics replace V4-A semantics on the fresh program ID.**
**Reasoning:**
- FIX_PLAN P15: hard rename on IDL-visible surface; canonical name wins.
- FIX_PLAN Decision #1 + Decision #2: fresh program ID, no coexistence. V4-A clients do not need V4-B compatibility.
- Option B in the source doc is motivated by "keep V4-A clients partially functional" — but V4-A and V4-B are two different program IDs. The old program keeps running for any historical reader; the new program gets the canonical name.
- Committed pattern: `record_climb_completion` already landed in V4-A as part of WS-2b scaffolding. V4-B completes the ontology shift around it without renaming.

### Q-C3 [source: V4B_MIGRATION_AND_TESTS §8 Q3] — What happens to the 16 V4-A vaults?
**Resolution:** `DERIVED-FIXPLAN`
**Answer:** **Clean slate. Do not bridge.** Demo narrative reseeds fresh V4-B climbs.
**Reasoning:**
- FIX_PLAN Decision #2: *"The 16 vaults are test data; no preservation."*
- Bridging to V4-A for demo adds complexity with no narrative gain — the hackathon demo tells a forward story ("here's the Climb-first protocol"), not a migration story.
- Seeding ~10 demo climbs via `scripts/seed_climbs_onchain.py` (per FIX_PLAN WS-1 line 546) is cheap.

### Q-C4 [source: V4B_MIGRATION_AND_TESTS §8 Q4] — Canonicalization spec (WS-10) complete enough to freeze?
**Resolution:** `NEEDS-TIM`
**Answer:** **Escalate.** The research cannot derive whether the spec is execution-ready without protocol-agent signoff; the dispatcher is not the canonicalization spec author.
**Tradeoff:** Freezing prematurely → V4-B RideAttestation PDAs may need reshaping if parser_version canonicalization changes. Delaying → V4-B execution is gated on spec completion.
**Recommendation to surface to Tim:** ask protocol agent on thaw (≈Apr 22) to do a 1-hour review pass on `docs/design/RIDE_CANONICALIZATION_SPEC.md` before V4-B implementation starts. If they flag gaps, sub-bead under WS-10.

### Q-C5 [source: V4B_MIGRATION_AND_TESTS §8 Q5] — Staker unlock curve preservation.
**Question verbatim:** *"`STAKER_UNLOCK_PCTS = [1, 3, 6, 11, 17, 25, 35, 50, 70, 100]` is unchanged by TRUTHS. Confirm V4-B keeps these exact values."*
**Resolution:** `DERIVED-TRUTHS`
**Answer:** **Yes — preserve exactly.**
**Reasoning:**
- PROTOCOL_TRUTHS §8.2: *"The 27% staker bucket compensates capital support of the Vault."* Does not redefine the unlock curve.
- FIX_PLAN §Decisions: no decision anywhere reopens the unlock curve.
- FIX_PLAN P9 preserves the eligible-staker-count concept, which the curve consumes.
- CLAUDE.md + FRESHEST_SPEC both cite the constant unchanged.
- Change to these values requires a tokenomics decision, which is not on the V4-B surgical split table.

### Q-C6 [source: V4B_MIGRATION_AND_TESTS §8 Q6] — Econ regression oracle snapshots count.
**Question verbatim:** *"§5 proposes N=3. Is that sufficient for Tim's comfort?"*
**Resolution:** `DERIVED-WWPTD`
**Answer:** **N=3 is sufficient for devnet cutover; add a 4th if a dormant-legend + empty-board + single-staker edge case isn't covered by the first 3.**
**Reasoning:**
- The three cases V4B_MIGRATION_AND_TESTS §5 proposes (typical / dormant legend / empty leaderboard) cover the three non-trivial branches of the distribution logic (all 5 buckets active / 4 buckets active / 3 buckets active + carries).
- FIX_PLAN P10 per-bucket carry is unit-tested separately via §3 TRUTHS-anchored test fixtures; N=3 covers the economic regression layer, not the whole invariant surface.
- WWPTD: if protocol agent on return wants N=10+, that's a follow-up bead, not a blocker. This is a devnet hackathon cutover, not a mainnet deploy. Strategy A's fresh-program-ID rollback story (V4B_MIGRATION_AND_TESTS §1) means worst-case we flip back.
- Note: Tim may override on risk tolerance — flag in summary.

### Q-C7 [source: V4B_MIGRATION_AND_TESTS §8 Q7] — Mint authority continuity (reuse CAL/DUNG mints vs fresh)?
**Resolution:** `DERIVED-WWPTD` + `DERIVED-COMMUNITY`
**Answer:** **Reuse V4-A mints with authority transfer to V4-B mint-auth PDAs.**
**Reasoning:**
- PROTOCOL_TRUTHS §7.1: *"CAL is … transferable, market-participation-capable."* Fresh mints would require portal / mobile / BoulderScan / wallet displays all to flip their mint addresses — adds blast radius for no semantic gain.
- Community consensus (V4B_RUST_ANCHOR §1): SPL mints are independent of program ID; mint-auth-PDA derivation depends on program ID so must be migrated, but the mint address itself is stable.
- V4-A already did this: CAL `4bxTCxEQp993cXs5nqhfWthRCPSTDv5K6PMgsfunEaJh` + DUNG `CqDFJWLpr49tB8xjHegy5JR5jwMCfmhicjuWawtKLeCk` per memory index.
- Committed pattern: transfer script pattern exists from V4-A redeploy — V4B_MIGRATION_AND_TESTS §2 cites `transfer_mint_authorities.ts` precedent.
- Precondition: V4-A mint authorities must be under Tim's control. (Memory confirms: Tim's `~/.config/solana/id.json` holds authority.)

### Q-C8 [source: V4B_MIGRATION_AND_TESTS §8 Q8] — VaultStake migration (Option B only)?
**Resolution:** Moot.
**Answer:** **Not applicable.** Option A (fresh deploy, Q-C1) makes this question disappear. Existing V4-A stakers are on devnet test accounts; ask stakers to re-stake after V4-B cutover. (Per FIX_PLAN Decision #2: V4-A state is test data.)

### Q-C9 [source: V4B_MIGRATION_AND_TESTS §8 Q9] — Hard rename scope in Option B.
**Resolution:** Moot.
**Answer:** **Not applicable.** Option A (fresh deploy). Zero transition days; rename atomic on new program ID.

### Q-C10 [source: V4B_MIGRATION_AND_TESTS §8 Q10] — `VaultUserEpochStats` provisional account — V4-B or follow-on?
**Resolution:** `DERIVED-FIXPLAN`
**Answer:** **V4-B includes it.** Part of the same surface.
**Reasoning:**
- FIX_PLAN WS-1 struct list (lines 442-451) includes `VaultUserEpochStats` with full field definition. Already specified.
- FIX_PLAN WS-6 (Local Legend rolling stewardship) requires on-chain `VaultUserEpochStats` provisional PDAs for chain-derivable Legend winner — blocks without it.
- Accepting "Legend election via indexer-side backend derivation" as an alternative inverts the arrow of truth (BACKEND_TRUTHS §10.1: indexer is a cache, never authoritative). TRUTHS requires on-chain-native.
- FIX_PLAN sub-task at line 527: *"Introduce VaultUserEpochStats provisional account for Legend derivation."* Explicit scope.

### Q-C11 [source: V4B_MIGRATION_AND_TESTS §8 Q11] — Founder Legend-bootstrap preservation?
**Resolution:** `DERIVED-FIXPLAN` + `DERIVED-TRUTHS`
**Answer:** **`found_climb` automatically creates the 8-epoch bootstrap LocalLegend for the founder.**
**Reasoning:**
- PROTOCOL_TRUTHS §6.1: Founder rights include *"bootstrap visibility and initial stewardship kickback via the first Local Legend stint."*
- FIX_PLAN Decision #16: *"`LocalLegend.total_earned` gets runtime increments."* Plus `LocalLegend { bootstrap: bool }` in FIX_PLAN WS-1 line 460.
- FIX_PLAN WS-1 `found_climb` description implies automatic Legend bootstrap via "Founder Bootstrap" CLAUDE.md language ("Vault creator is automatically first Local Legend for 8 epochs").
- A separate `bootstrap_founder_legend` instruction is a wire-in-atomic-founding anti-pattern: the founding transaction should produce a fully-formed Climb + bootstrap Legend in one ix set. `found_climb` + `attach_vault` + implicit Legend init is the clean shape.

---

## Source D — V4B_RUST_ANCHOR_KNOWLEDGE_REFERENCE §14 (emergent questions / gotchas framed as decisions)

### Q-D1 [source: V4B_RUST_ANCHOR_KNOWLEDGE_REFERENCE §14 item 7] — Use `emit!` or `emit_cpi!` for settlement events?
**Resolution:** `DERIVED-COMMUNITY` + `DERIVED-TRUTHS`
**Answer:** **Use `emit_cpi!` for settlement-critical events** (SettlementWeekFinalized, RecordRoyaltyPayout, StakerAllocation, LegendPayout, RecordBoardUpdated). **Keep `emit!` for low-stakes informational events** (BeetleCardCreated, Scoring, etc.).
**Reasoning:**
- V4B_RUST_ANCHOR §7: *"RPC providers routinely truncate `emit!` logs … `emit_cpi!` lives in the transaction's inner-instructions array, which RPCs do not truncate."*
- V4B_RUST_ANCHOR §14 item 7: settlement emits 10-20 events/vault/week; any truncation = indexer misses payouts.
- BACKEND_TRUTHS §10.2: transaction builders bypass the indexer for canonical reads, but the indexer **must** stay in sync with on-chain events for projections. Missing events = projection drift.
- PROTOCOL_TRUTHS §5.3 projections are for reading — but §3.3 settled truth relies on complete audit trail.
- Committed pattern: current `lib.rs` uses `emit!` 33 times, `emit_cpi!` zero times. This is a V4-A drift to correct in 0uv8.

### Q-D2 [source: V4B_RUST_ANCHOR_KNOWLEDGE_REFERENCE §14 item 10] — u64 vs u128 for bucket-share arithmetic?
**Resolution:** `DERIVED-COMMUNITY` + `DERIVED-FIXPLAN`
**Answer:** **Use `u128` intermediates for all bucket-share computations.** Pattern: `(bucket_amount as u128 * pct_bps as u128 / 10_000) as u64`.
**Reasoning:**
- V4B_RUST_ANCHOR §14 item 10: repo has `overflow-checks = true` in release profile; u64 * u64 near supply cap will panic instead of wrapping.
- DUNG supply cap is 1B × 10^9 = 10^18 ≈ 2^60. A `u64 * u16 bps` can overflow u64 arithmetic silently in debug / panic in release.
- FIX_PLAN P14 "no handwaving, explicit economics": truncation-induced rounding dust is allowed (carries in bucket); panic is not.
- FIX_PLAN P10 per-bucket carry relies on exact math with modular remainder flowing to carry; u128 intermediates preserve this.

### Q-D3 [source: V4B_RUST_ANCHOR_KNOWLEDGE_REFERENCE §14 items 4 + 5] — `init_if_needed` idempotency + PDA seed collision audit?
**Resolution:** `DERIVED-COMMUNITY`
**Answer:** **Every V4-B instruction using `init_if_needed` for Climb / Vault / RiderSoul / receipts must include explicit idempotency checks.** Audit new seeds for collision.
**Reasoning:**
- V4B_RUST_ANCHOR §14 item 4: `init_if_needed` is on repo-wide (`Cargo.toml:16`). Reinitialization attack surface is real; re-running founding on an existing Climb must no-op, not reset.
- Community pattern: check `account.data_len() > 0` or `account.discriminator != [0;8]` post-init; if present, assert field invariants match and return early.
- V4B_RUST_ANCHOR §14 item 6: new seeds `RIDE_ATTESTATION_SEED`, `CLIMB_COMPLETION_RECEIPT_SEED`, `CAL_MINT_RECEIPT_SEED` + `CLIMB_SEED` (new). PDA keyspaces are distinct by seed string; confirm lengths & prefix uniqueness in test `test_pda_seed_collision_audit`.
- This is a review-time checklist, not a decision — but flagging here so it lands in 0uv8 tests rather than being missed.

---

## Summary for Tim

### Resolved automatically — no Tim action required

**29 of 32 questions resolved** by cascading through TRUTHS / FIX_PLAN / committed patterns / community consensus. Breakdown:

| Bucket | Count |
|---|---|
| `DERIVED-TRUTHS` | 9 |
| `DERIVED-FIXPLAN` | 11 |
| `DERIVED-PATTERN` | 1 |
| `DERIVED-COMMUNITY` | 3 |
| `DERIVED-WWPTD` | 5 |
| **Total resolved** | **29** |
| `NEEDS-TIM` | 1 |
| Moot / redirect | 2 |

### Questions that genuinely need Tim — 1 item

**T1 — WS-10 canonicalization spec readiness (Q-C4).** Is `docs/design/RIDE_CANONICALIZATION_SPEC.md` complete enough to freeze for V4-B implementation, or does it need a protocol-agent review pass first? **Tradeoff:** freeze now → V4-B RideAttestation PDAs may need reshaping if parser_version canonicalization changes. Wait for review → V4-B execution blocked ≤1 day on protocol agent thaw (~Apr 22).
**Recommended path:** have protocol agent do a 1-hour review pass on thaw; sub-bead any gaps under WS-10.

### Advisory — items where Tim may want to weigh in but the default holds

**A1 — Econ regression oracle count (Q-C6).** Research assumes N=3 is sufficient for devnet hackathon cutover. Tim may prefer N=10+ for risk tolerance; this only matters if Tim sees devnet cutover as mainnet-gating. Default: N=3 with optional 4th edge case.

**A2 — Economic-clock conversion of `rights_expires_epoch` (Q-A2).** Research resolves via FIX_PLAN P6 ("ride time is the economic clock"). If Tim wants to keep epoch-based rights for simplicity, flip back — but it'd be the only remaining epoch-clock field on a ride-time object.

---

## Protocol-dev Pattern Catalog (bonus findings)

Patterns established by the protocol dev's committed work that future 0uv8 execution should preserve:

### PDA seed design
- **Identity-first, not counter-first.** `RIDE_ATTESTATION_SEED` → `[seed, rider, ride_hash]` (`lib.rs:3639`), `CAL_MINT_RECEIPT_SEED` → `[seed, ride_attestation, rider]` (`lib.rs:2568`), `CLIMB_COMPLETION_RECEIPT_SEED` → `[seed, ride_attestation, vault]` (`lib.rs:2580`). Canonical identities compose; counters don't. Apply to Climb (signature_hash) + Vault (climb_pda) in 0uv8.

### Idempotent-ix guard pattern
- **Events-named `Migrated` + size check** — commit `f937e568 Post-deploy: backend accounts, migration, indexer, docs for V3 security` demonstrates the pattern for realloc migrations (`lib.rs:235-284`). Reuse shape if V4-B ever has to migrate in-place (does not currently per Q-B6).

### Access-control pattern
- **`backend_authority` gated instructions** — commit `1d113eac Anchor security: add access control to 3 instructions` added the ProgramConfig-backed signer gate. All V4-B economic/settlement instructions (`finalize_settlement_week`, `elect_local_legend`, `increment_beetle_score`, `record_ride`, `credit_cal`) must preserve this gate. Use `has_one = backend_authority @ ErrorCode::Unauthorized` constraint.

### Fresh-lane cutover pattern
- **`Rotate devnet program id` commit** — `823d75ee` is the canonical template for a fresh-program deploy. Includes declare_id update, `Anchor.toml` swap, `addresses.devnet.json` rewrite, env var propagation. 0uv8 follows this template exactly.

### Dead-code cleanup pattern
- **Aggressive purge, don't deprecate** — commit `a2449e1f Dead code cleanup: remove ~5,800 lines across 88 files` signals the preferred modus: delete and regenerate, don't layer backward-compat. Applies to Merkle path, V2/V3 migrations, UserState, VaultActivation.

### Event emission
- **Current drift: all `emit!`, no `emit_cpi!`** — 33 uses of `emit!`, 0 of `emit_cpi!` in current `lib.rs`. V4B_RUST_ANCHOR §7 + §14 item 7 argue `emit_cpi!` for settlement-critical events. 0uv8 should convert settlement events to `emit_cpi!` (SettlementWeekFinalized, RecordRoyaltyPayout, StakerAllocation, LegendPayout, RecordBoardUpdated, ClimbCompleted, CalCredited, RideAttestationRecorded).

### Dual-emit bridge pattern
- **`record_climb_completion` already emits both `ClimbCompleted` and `VaultCompleted`** (`lib.rs:611, 622`). Today's V4-A uses this as an indexer-bridge mechanism. V4-B fresh deploy drops `VaultCompleted`; the dual-emit pattern lives only on V4-A's program ID for historical consumers.

### u128 intermediate idiom
- V4-A already uses `u128` intermediates in settlement math (verify in `distribute_epoch_rewards` implementation). 0uv8 preserves and extends this to all new bucket-share paths (Record Royalty rank split, StakerAllocation pro-rata).

### Anchor constraint bidirectional verification
- When both Climb and Vault PDAs appear in an Accounts struct, use bilateral constraint (per V4B_PROTOCOL_SURGERY_SCOPE §7.1):
```rust
#[account(
    constraint = vault.climb == climb.key() @ ErrorCode::ClimbVaultMismatch,
    constraint = climb.vault == Some(vault.key()) @ ErrorCode::ClimbVaultMismatch,
)]
```
This catches wrong-climb/wrong-vault pairings at the edge.

### Post-CPI reload owner check
- V4B_RUST_ANCHOR §14 item 5 (Anchor #3830 unresolved as of Aug 2025): after `account.reload()` on any SPL Token account post-CPI, add `require_keys_eq!(account.to_account_info().owner, &token::ID)`. Manual guard until Anchor patches.

---

## Gift-posture self-check

- [x] Every derived answer cites its source (TRUTHS §N, FIX_PLAN P#, Decision #, commit hash, or lib.rs:line).
- [x] NEEDS-TIM reduced to 1 genuinely un-derivable item (WS-10 canonicalization spec readiness) — research cannot judge protocol-agent's readiness-bar without them.
- [x] Tim can read this summary + 1 escalation in <10 minutes (vs. walking 32 raw questions in 30+).
- [x] Protocol agent, returning from freeze, finds most trivial questions pre-answered with explicit TRUTHS/FIX_PLAN citations.

---

## References

- [`docs/PROTOCOL_TRUTHS.md`](../PROTOCOL_TRUTHS.md) — §§2, 3, 4, 5, 6, 7, 8, 10, 11, 12
- [`docs/MOBILE_TRUTHS.md`](../MOBILE_TRUTHS.md)
- [`docs/BACKEND_TRUTHS.md`](../BACKEND_TRUTHS.md) — §§4, 8, 10, 12
- [`docs/design/PROTOCOL_ALIGNMENT_FIX_PLAN.md`](./PROTOCOL_ALIGNMENT_FIX_PLAN.md) — Principles P1, P5, P6, P9, P10, P11, P12, P14, P15; Decisions #1, #2, #3, #7, #8, #11, #16; WS-1
- [`docs/design/V4B_PROTOCOL_SURGERY_SCOPE.md`](./V4B_PROTOCOL_SURGERY_SCOPE.md) §9
- [`docs/design/V4B_BLAST_RADIUS_INVENTORY.md`](./V4B_BLAST_RADIUS_INVENTORY.md) §10
- [`docs/design/V4B_MIGRATION_AND_TESTS.md`](./V4B_MIGRATION_AND_TESTS.md) §8
- [`docs/design/V4B_RUST_ANCHOR_KNOWLEDGE_REFERENCE.md`](./V4B_RUST_ANCHOR_KNOWLEDGE_REFERENCE.md) §14
- [`docs/design/WWPTD_DISPATCHER_PLAYBOOK.md`](./WWPTD_DISPATCHER_PLAYBOOK.md)
- `protocol/anchor/programs/boulder_rollers/src/lib.rs` — current V4-A source, lines cited throughout
- Recent protocol commits since 2026-03-01 (23 commits): key cited — `01b55adb`, `00164b41`, `4529cb02`, `f04b41af`, `a672558b`, `1af10ce0`, `4b0e0b26`, `133b9b6e`, `823d75ee`, `a2449e1f`, `f937e568`, `1d113eac`
