# Boulder Roller Math Audit — July 2026

**Status:** BASELINE LEDGER. Compiled 2026-07-09 from the first audit sweeps.
`docs/design/MATH_AUDIT_PHASE2_2026-07-12.md` is the current correction and completeness
addendum; its correction ledger supersedes blanket clean bills and stale finding titles in
this document. Items marked **[Tim-ratifies]** touch protocol semantics and go to the
weekly session. Everything else is agent-autonomous bead material.

**Ratified 2026-07-09 (Tim):**
- **Hill repeats (1.5):** count Strava-style — every ascent is an effort. Tim 2026-07-09:
  the on-chain effect is inherent in the tribute (per-ascent tribute summed carries the
  economic weight), so backend aggregation (best time + summed tribute, one call) is the
  accepted shape; per-ascent completion count follows at V4-B.
- **Late uploads (1.4) — RATIFIED 2026-07-09 as the flow-meter model:** the vault stops
  asking rides "which week are you?" Tribute is a lifetime accumulator on the climb;
  the settlement week is only the payout heartbeat (pays whatever accumulated since last
  finalization). Records are timeless — old rides enter the board at original
  `completed_at`. Retires `RideOutsideSettlementWindow` as live behavior and stops new
  next-week writes; the enum slot and account fields remain for ABI/layout compatibility,
  and legacy next-week values drain on rollover. Gaming surface is unchanged, bounded by
  the 30-day CAL cap. Chain gets simpler. WWPTD framing: rides are evidence, the climb
  accumulates.
- **Ties (2.2):** no decimal times — 1 Hz GPS makes sub-second precision false. Standard
  competition ranking (golf/athletics): tied riders consume the tied spots (two tied at
  2nd occupy 2nd+3rd, split those pooled shares equally; next rider reads 4th and takes
  rank-4 share). Display shows T-2, replacing first-achiever-wins so paid == displayed.
- **Staking eligibility (2.3):** engineering call — drop the `+1`; stake mid-week N earns
  at week N+1's settlement (first full week staked). Matches spec language as written.
- **Emissions (2.5):** auto-halving inside `distribute_epoch_rewards`; rider copy states
  the current season's conversion rate instead of a fixed "1000 CAL = 1 DUNG" promise.

**Scope covered:** effort math (TSS/NP/CAL), tribute + settlement (backend + Anchor),
climb detection + signatures + vault matching, canon compiler v0.1, DB functions,
API routes, indexer, Strava import, economic ledger, fitness analytics, sensor integrity,
plus a 40-week settlement simulation and cross-layer lifecycle analysis.
**First-pass exclusions:** mobile, Anchor account-constraint security, parser resource
bounds, transaction confirmation, and full crank recovery. Phase 2 covers the economically
material parts of those exclusions. Road-attribution/achievements/tile-history display
math remains low-stakes residual scope.

**The three recurring patterns.** Nearly every serious finding is one of:
1. **The same math implemented twice, with the weaker copy live** (§Census).
2. **Validation living on a layer that doesn't pay** (DB validates, chain doesn't).
3. **Two policies about the same question that never met** (30-day CAL window vs
   ~14-day tribute window; spec vs code on staker remainder).

**What's verified sound:** bucket bookkeeping conserves integer amounts in the modeled
scenarios, ride-hash canonicalization has a fixed reference vector, indexer u64 handling is
string-exact, DB time validation is explicit, Strava uses the normal parser pipeline, LP
mint/redeem uses u128 pro-rata math, and the geometric utilities are conventional. Phase 2
shows that settlement fairness, solvency, and liveness are **not** certified by the
conservation simulation.

---

## Tier 1 — Money is wrong or silently lost today

### 1.1 Invalid times reach the permanent record board
`validate_climb_time` runs and sets `completion_validated`, but the on-chain
`record_climb_completion` (KOM + leaderboard + tribute) executes regardless
(`backend/app/services/climb_economy_processor.py:293`); on-chain the only check is
`time > 0`. The DB layer (048_time_validation.sql) enforces bounds with exceptions and an
admin review view — every layer validates except the one that pays. One impossibly-fast
time takes rank 1 of a **permanent** 55%-forever annuity.
**Fix:** gate the chain call on `completion_validated`; at V4-B move min/max time bounds
on-chain per vault.

### 1.2 v1 signature similarity is mathematically void and is the live economic fallback
v1 similarity = Hamming distance over `SHA256(profile)` (`climb_signature.py:83`).
Avalanche ⇒ gradient term ≈ 0.5 for *everything*; score ≈ 0.25 + metric sims; a different
climb with similar vert/gradient/distance scores ~0.75 > the 0.70 reward threshold. The
fallback SQL has **no geographic gate** (vert-range over all vaults globally,
`vault.py:483`) and the economic caller never passes the v2 signature
(`climb_economy_processor.py:152`). Wrong hill can get paid.
**Fix:** reward-grade matching requires a geometry gate (PatternEngine GPS-gated or v2
DCT multi-gate). v1 similarity demotes to display/discovery only.

### 1.3 FTP self-report is a CAL printing press
TSS ∝ NP²/FTP² (`ride_metrics.py:262`); FTP is user-entered, unclamped. Halving claimed
FTP ⇒ 4× CAL with genuine power data. `DEFAULT_FTP_W=200` inflates strong riders who
never set FTP.
**Fix:** server-derived FTP (rolling best 20-min × 0.95 from the rider's own attested
history), CAL denominator = max(user, derived); clamp rewardable IF ≤ ~1.15 (>1h) and
TSS ≤ ~120/hr. Policy layer only (`ride_effort_policy.py`).

### 1.4 Late rides earn CAL but completions silently vanish  **[Tim-ratifies window]**
**Resolved 2026-07-14 by `boulderroller-v2-lrwd`.** The canonical receipt-backed
completion path now credits the oldest open lifetime tribute flow after
empty-week catch-up and keeps the original ride timestamp/epoch for record
provenance. The receipt-less legacy handler remains ABI-visible but fails
closed. Completion remains ahead of CAL in the retryable backend coordinator.
The paragraph below is the pre-fix failure mode; exact delayed-flow
finalization projection is tracked by `boulderroller-v2-4x3v`, and retirement
of disabled legacy clients/smoke paths is tracked by `boulderroller-v2-29rm`.

`credit_cal` accepts rides ≤30 days old; `credit_tribute_for_week` accepts only the open
settlement week or open+1 (`lib.rs:4313`). Older ⇒ `RideOutsideSettlementWindow` ⇒
`VaultCompletionChainError` ⇒ swallowed by per-climb `except: log, continue`
(`climb_economy_processor.py:226`). A PB uploaded 10 days late: CAL mints, record-board
entry lost **forever**, silently. Worse: if the distribution crank stalls >1 week on an
active vault (`maybe_advance_empty_settlement_week` only advances *empty* weeks),
**current** completions get dropped too — crank downtime silently voids the product loop.
**Fix:** align the two windows (either tribute accepts N weeks back with per-week buckets,
or CAL window shrinks to match); make the failure loud (rider-visible "counted late /
not counted" state); alert when any vault's open week lags now by >1.

### 1.5 Hill repeats count once per ride
Completion receipt PDA is seeded `[seed, ride_attestation, vault]` (`lib.rs:4924`), so the
second+ ascent of the same climb in one ride fails account-init and is swallowed by the
same generic except. A 10× hill-repeats session records one completion, one tribute
share, and whichever ascent the pattern loop hits first (not the fastest) as the time.
**Fix:** include an ascent ordinal in the receipt seeds, or aggregate repeats
backend-side (best time + summed tribute) into one chain call. Decide the product
semantics first ("do repeats count?"). **[Tim-ratifies semantics]**

### 1.6 Tribute is not conserved
**Resolved 2026-07-14 by `boulderroller-v2-zxoz`.** Completion-plan construction
preserves each climb's raw relative weight and, only when their aggregate exceeds
the ride's exact CAL, normalizes them to that budget with deterministic
largest-remainder apportionment (vault ID breaks equal-remainder ties). Plan freeze and
the PostgreSQL review boundary reject over-budget plans. On-chain, a writable
ride-scoped `RideTributeBudget` PDA serializes completions and rejects any aggregate
overrun before vault, leaderboard, or receipt state changes.

**Original finding.**
`cal_tribute = cal_earned × time_weight × intensity(≤1.3)` per climb
(`climb_economy_processor.py:262`): one steep-climb ride tributes 130% of earned CAL;
overlapping detections compound; nothing is deducted or burned (`total_cal_burned` burns
nothing). DUNG emission is driven by an unconserved number.
The remaining `total_cal_burned` rename belongs to the V4-B terminology cutover.

### 1.7 Economic ledger: float money + hash-chain race
`economic_events` stores `amount`/`balance_after` as `float()` while hashing Decimals
(`economic_ledger.py:222`); and `record_event` is read-last-then-insert, non-atomic —
concurrent events for one wallet fork the hash chain and corrupt the running balance.
**Fix:** NUMERIC/string storage; serialize per (wallet, denomination) via DB function or
advisory lock.

### 1.8 LP withdrawal strands principal dust
Withdraw routes require whole-number LP × 1e9 (`routes/vaults.py:1502,1691`) but LP is
minted by truncated pro-rata division, so balances end fractional. Final exit can never
clear the remainder.
**Fix:** accept base-unit LP amounts, or a withdraw-all path reading exact
`stake.lp_tokens`.

---

## Tier 2 — Wrong soon, or rider-visible now

### 2.1 Epoch→date conversions missing the anchor (dates in 1972)
`GET /epoch/current` computes `ends_at = (epoch+1) × 604800` without adding
`EPOCH_ANCHOR` (`routes/distributions.py:420`) — the settlement countdown returns July
1972. Same bug for legend `elected_at`/`term_ends_at` (`repositories/vault.py:1234`). The
correct helper `get_epoch_start_time()` exists in `solana_direct.py:4104`, unused.
**Fix:** one epoch-time module; delete local re-derivations.

### 2.2 Tie semantics are not the ratified pooled-rank rule
The primary portal reads the indexed on-chain array, so its current order and payout order
match. The remaining inconsistency is inside the authoritative lifecycle: historical seed
sorts ties by `recorded_at`, live updates retain stable ingestion order, and neither path
implements the ratified standard-competition rank with pooled tied-place shares.
**Fix:** implement the ratified pooled tie rule in chain payout, indexer/API rank fields,
and display. **[Tim-ratifies rule — ratified 2026-07-09]**

### 2.3 Staking eligibility off-by-one vs spec  **[Tim-ratifies]**
`compute_eligible_from_epoch` = first-full-epoch **+1** (`lib.rs:4481`): stake mid-week N
⇒ first earn at week N+2's settlement, despite being staked for all of N+1. Spec says
"effective next Settlement Week."
**Fix:** drop the `+1`, or amend the spec to "one full probation week." One line either way.

### 2.4 Staker-unlock remainder: code contradicts CLAUDE.md  **[Tim-ratifies]**
Locked portion carries within the staker bucket (`lib.rs:3061`); CLAUDE.md says it goes to
the leaderboard. Carry is arguably better; one document is wrong. Also: unlock curve is
sybil-cheap (10 × 100-CAL wallets = full unlock).
**Simulation quantified:** a permanent single-staker vault accumulates ~2.6 DUNG/week of
promised-but-unmintable carry — 106 DUNG (22% of all emissions) in limbo after 40 weeks,
unbounded (§Simulation).

### 2.5 Halving: manual, and "1000 CAL = 1 DUNG" silently breaks
`apply_emission_rate` scales pending DUNG; the un-emitted remainder is discarded at roll;
halving is admin-triggered; integer-halves to 0 after 14 halvings.
**Simulation quantified:** after halving, 50% of tribute-implied DUNG is destroyed weekly;
realized ratio fell to 82.5% within 14 post-halving weeks and decays toward 50%+ loss.
**Fix:** auto-halve inside `distribute_epoch_rewards`; decide tail policy; fix rider copy
to state the current conversion rate, not a constant. **[Tim-ratifies emission story]**

### 2.6 CTL collapses after a riding gap
Missing yesterday-row ⇒ `prev_ctl = 0` (`fitness_analytics.py:32`): a CTL-50 rider back
from 3 weeks off shows ~1 instead of ~30. BeetleCard Mana = CTL.
**Fix:** seed from last stored row decayed `× exp(−gap/42)` (ATL: /7). Three lines.

### 2.7 v2 matching fails silent-dark
`ClimbSignatureV2.similarity` wraps the Rust matcher in `except: return 0.0`
(`climb_signature.py:395`); a broken `workout_parse` import (compiled maturin artifact)
silently downgrades all matching to the broken v1 path. Docstring claims a Python
fallback that doesn't exist.
**Fix:** fail loud; startup health check "workout_parse importable + match_signatures_v2
callable."

### 2.8 Unit fragility around the 1000-CAL threshold
`VAULT_CAL_TO_DUNG_THRESHOLD = 1_000` bare divisor works only because CAL and DUNG both
have 9 decimals; `VAULT_CREATION_CAL = 1000` is *display* units (×1e9 at `lib.rs:1338`);
`admin_create_vault.cal_deposited` unit is undeclared. Three look-alike constants, three
unit semantics, zero comments.
**Fix:** explicit conversion fn + static assert CAL_DECIMALS == DUNG_DECIMALS; document
units at every boundary.

### 2.9 Settlement crank trust + cap-edge failures
`distribute_epoch_rewards` derives unlock % and pro-rata shares from whatever stake
accounts the backend passes: duplicates double-count (unlock AND allocation), omissions
silently carry. `rewards_earned` is allocated at settlement but supply-cap-checked at
harvest (allocations can become unmintable); per-leaderboard-entry `can_mint` `require!`
bricks finalization at cap exhaustion.
**Fix (V4-B batch):** dedupe stake accounts by pubkey; reserve Community-cap headroom at
allocation; convert cap-require to skip+carry.

### 2.10 Effort-measurement biases (live Python implementation)
NP drops missing/zero-power records (coasting inflates NP; `ride_metrics.py:232`); TSS and
`time_weight` denominators use elapsed (not moving) time; HR-only tier pays par with
power off avg-HR vs defaulted max-HR 190 (≤100 TSS/hr, spoofable); 1 Hz assumed in two
places. Ride re-upload with 1 byte changed = new ride_hash = double CAL (known V4-B gap).
**Fix:** superseded by §3.1 consolidation (the Rust engine already fixes NP + moving
time); discount HR tier (~70%) until the trusted-sensor lane lands.

---

## Tier 3 — Canon compiler (v0.1, not frozen — fix while wet)

File: `workout-parse/src/canon/mod.rs`.

- **C1 — "high" confidence unreachable:** `topographic_isolation_not_scored_v0` is pushed
  unconditionally (:557), and the tier fn requires `flags.is_empty()` for "high" (:1394)
  despite carving that flag out of `material_flags`. Everything caps at "medium".
- **C2 — corridor cells are centerline-only:** res-10 cells of profile points, no k-ring,
  despite 25m gate half-width config (:1560). Edge-of-road GPS lands outside the set;
  traversal verification will false-miss. K-ring-1 the centerline; widen gates.
- **C3 — third vert/gradient semantics:** canon vert = net rise (:533); ride ascent =
  positive-delta sum; refinement avg_gradient = ascent/distance. The mismatch surfaces at
  cutover when canon numbers meet ride evidence. Pick one rider-facing definition.
- **C4 — one direction per OSM way:** `orient_uphill` endpoint comparison; the opposite
  ascent of a crest/both-sides road is never compiled (:1078).
- **C5 — identity churn:** fingerprint hashes first/last coords at 1e-7° (:1598);
  a boundary-snap shift or DEM re-export mints a new identity. Anchor to OSM node ids.
- **C6 —** 1m distance floor lets duplicate points inject absurd max-gradient into
  worthiness (:1448). Dedupe zero-distance pairs.
- **C7 —** "corridor" WKT is an axis-aligned bbox (:1504) — massively over-covers
  diagonal roads. Audit consumers.
- **C8 (note)** — worthiness saturates at 100 from vert alone ≥ ~184m; tiers are mostly a
  vert ranking at Philly scale. Revisit for bigger terrain.
- **Canon acceptance criterion (from detector lessons):** traversal verification must use
  map/DEM distance — never time × assumed speed (see §4.1).

---

## Tier 4 — Detection & signatures (tuning frozen; document, don't retune)

- **4.1 Momentum-lane "gradient" is speed-dependent:** elev / (time × 5 m/s) even when GPS
  exists (`detector.rs:534`) ⇒ that lane's detection sensitivity scales with rider speed;
  slow riders' steep climbs get missed; `MIN_CLIMB_VAM=300` compounds. Scope confirmed by
  deep-read: the persistence lane and boundary refinement use true haversine distances
  (`persistence.rs:2206`, `refinement.rs:378`) — the bias is confined to the
  momentum/legacy segmentation half of the canonical_v2 fusion. Don't touch (frozen,
  demoting to discovery); record in DETECTOR_PARAMS.md; forbid the pattern in canon
  verification.
- **4.1b Persistence core verified sound:** the 0-dim persistent-homology implementation
  (union-find sublevel filtration, elder rule, deterministic tie-breaks,
  `persistence.rs:312`) is textbook-correct; no money-class bugs in the core. The risk in
  this file is the ~60 corpus-fitted constants (4.5), not the algorithm.
- **4.2 v1 exact-match tier nearly dead:** signature bytes include per-ride `duration_s`,
  so exact hash requires reproducing duration to the second. (Identity contaminated with
  evidence — canon-first was right.)
- **4.3 v2 DCT distance compressed by baseline offset:** gradient bins carry a constant
  offset that inflates the relative-distance denominator; DC term dominates the 6-coeff
  comparison. Thresholds are corpus-tuned around it — don't retune; carry the lesson to
  canon commitment comparison.
- **4.4** Dead direction bit (always false) inside checksummed signature bytes
  (`signature_v2.rs:267`); f16-stored vs f32-fresh coefficient asymmetry (minor).
- **4.5** ~60 corpus-fitted constants in `persistence.rs` with sample-count units assuming
  1 Hz; `detector-param-guard` watches the dead Python detector
  (`patterns/climb.py`, 3,485 lines) instead of the live Rust constants.
  **Fix:** re-point the guard; schedule the legacy Python detector for deletion.
- **4.6** Record-board times are detector-boundary elapsed times — riders aren't timed
  over the same span. **[Tim-ratifies]:** do record boards re-baseline at canon cutover
  (gate-to-gate timing)? If not, pre-canon times permanently outrank post-canon ones.

---

## Duplicate-math census

Every quantity computed in ≥2 places. Divergent = confirmed different results.

| Quantity | Implementations | State |
|---|---|---|
| TSS/NP | Python `ride_metrics` (LIVE, flawed) · Rust `metrics.rs` (correct, dead) · adapter shim (NP=avg×1.05, dormant) | **Divergent** |
| CAL from TSS | policy 1:1 (LIVE) · Rust `calculate_cal_earned` IF-multipliers (dead, exported) | **Divergent** |
| Tribute | executor TSS-share base-units (LIVE) · pattern_engine `vert/100` display-units (computed, attached to results) | **Divergent** |
| Tie-break | DB first-achiever (display) · on-chain none (pays) | **Divergent** |
| Time validation | DB bounds+exception · Python fallback · on-chain none (pays) | **Divergent** |
| Epoch→time | Rust `lib.rs` (anchor) · `solana_direct` (anchor) · `distributions.py` (NO anchor) · `vault.py` (NO anchor) | **Divergent** (2.1) |
| Vert | ride ascent Σ+Δ · canon net rise · v1 sig Σ+Δ | **Divergent** (C3) |
| Avg gradient | live ClimbV2 net/dist (=tribute input) · refinement ascent/dist (computed, discarded) · v2 sig net/dist · canon net/net · detector VAM-proxy | **Divergent** (C3, 4.1, 9.4) |
| Elevation smoothing | Python SMA(21) · Rust window(5) · canon window(3) | Different by design; document |
| Elevation gain | Python `ride_metrics` · adapter copy · Rust cumulative-ascent | Near-parity; consolidate with 3.1 |
| Haversine | Python ×2 · Rust utils · canon | Identical formula; fine |
| Similarity | v1 Python Hamming (LIVE fallback) · v2 Python→Rust wrapper · Rust multi-gate | **Divergent** (1.2) |
| Duration | elapsed (metrics, tribute weights) · moving (Rust, unused) · SQL bounds assume moving | **Divergent** |
| Climb detection | Rust canonical_v2 (LIVE) · Python legacy 3,485-line copy | Legacy scheduled for deletion (4.5) |

### 3.1 The consolidation fix (single bead, closes most of the census)
Promote Rust `compute_metrics` to the only TSS/NP engine (fixes NP-zeros + moving-time);
make Python `calculate_metrics` a wrapper; **delete** the avg×1.05 shim, the dead Rust CAL
multiplier, and pattern_engine's vert-tribute; one epoch-time module. Golden-corpus
before/after diff as the regression gate.

---

## Settlement simulation (2026-07-09)

Faithful integer-math port of `distribute_epoch_rewards` + tribute buckets + carries +
halving + unlock curve; 40 weeks × 4 scenarios (steady, cold-start, single-whale-staker,
halving at week 26). Script: `scripts/settlement_sim.py` (worth promoting to `tests/` as
a property test).

**Certified only:** all four bookkeeping invariants held every week — split conservation
(dust→record royalty exact), minted+carried == available, CAL→DUNG conversion lossless mod
remainder, and staker allocation ≤ the amount labeled unlocked in that call.

**Not certified:** fairness, liability solvency, or crank liveness. Phase 2 demonstrates
that prior locked staker carry is re-unlocked every week, staker claims are not reserved
against the Community cap, and queue/cursor composition can strand weeks. Run
`scripts/reproduce_settlement_lifecycle_failures.py` for the counterexamples.

**Quantified behaviors** (referenced above): single-staker limbo grows unbounded
(106 DUNG = 22% of emissions after 40 wks — §2.4); post-halving the 1000:1 story is
82.5%-true and falling (§2.5).

---

## Sweep 7 — Re-execution paths, elections, activation seeding, portal telemetry (2026-07-09)

- **7.1 DB completion evidence diverged from chain truth.** Before the receipt-backed
  coordinator, `record_completion` (DB) could commit before an on-chain rejection and
  leave DB-derived legend/activation inputs ahead of chain truth. LRWD removes the
  late-ride rejection and the coordinator now checkpoints completion before CAL with
  retryable recovery. Hill-repeat conservation and any remaining legacy-row repair stay
  separate; do not reintroduce a best-effort swallow path.
  Follow-up `8346` closed the remaining amount-authority gap: historical V1
  receipt evidence remains identity-only, while V2 stores and hashes exact
  tribute. New V1 writes fail closed, pending V1 plans enter review, and finality
  now requires version/hash/vault/amount equality.
- **7.2 Falsy-zero coercion idiom.** `getattr(rec, "power_w", None) or dict.get(...)`
  treats power 0 W and elevation 0.0 m as missing (`replay_service.py:1000`). Currently
  confined to the analysis-only replay path, but Philadelphia rides near sea level —
  keep this idiom out of production mappers (lint/convention note).
- **7.3 Portal telemetry (display-only).** Cursor gradient is raw point-to-point with no
  smoothing (`rideTelemetry.ts:117`) — a 1m barometric step over 5m shows 20%; disagrees
  with backend smoothed gradients. Timestamp parsing magnitude-sniffs and falls through
  to `Date.parse(String(n))` for small numerics — V8 parses "3600" as year 3600, so
  offset-seconds streams can misalign chart cursors. Brittle; fine until riders notice.

**Clean in sweep 7:** replay pipeline (no production writes, correct diff framing);
backfill (evidence-only, idempotent by activity id); vault activation seeding
(validated-only rows, unique-rider top-10, KOM from same rows — the seeding path respects
validation even though the live path doesn't, cf. 1.1); legend election derivation
(validated filter + deterministic tie-break: count desc → earliest completion → wallet;
uses correctly-anchored epoch time); portal haversine.

## Sweep 8 — Full-coverage pass: money services, economics SQL, DEM exporter, admin surfaces (2026-07-09)

- **8.1 `dung_supply_state` is orphaned — supply monitoring is dead.** Nothing in the
  codebase writes the table; its only reference is the migration that created it
  (032_supply_emissions.sql). The admin Supply gauge reads it, so the dashboard shows
  0 minted forever while real supply accrues on-chain in `DungMintState`. This is the
  surface that would warn of cap exhaustion (cf. 2.9) — it's disconnected.
  **Fix:** indexer writer projecting `DungMintState` → `dung_supply_state` (base→display
  ÷1e9), or admin API reads the chain account directly.
- **8.2 SupplyGauge hardcodes Team/Investor/POL minted = 0** even when live data is
  supplied, and duplicates cap constants client-side (`SupplyGauge.tsx:56`). Misinforms
  the moment those buckets mint.
- **8.3 Terrain classification is duration-confounded.** Classes come from absolute
  per-ride gain (200/600/1500 m, `terrain.rs:195`): a long flat ride accumulates enough
  noise-gain to classify "hilly," silently switching terrain-adaptive detector
  thresholds. Frozen-adjacent — log as known bias; use gain-per-km if/when the detector
  unfreezes (and never port absolute-gain classing into canon).
- **8.4 Points-era SQL functions still deployed.** `calculate_lp_tokens` /
  `stake_points` (033_vault_economics.sql) mutate `vault_stakes` and reference removed
  points columns. If exposed via Supabase RPC, a stale caller could write stake rows the
  chain knows nothing about. Remove with a cleanup migration.
- **8.5 DEM exporter registration check (low).** Bilinear sampler and north-up transform
  are correct; pixel-is-area vs pixel-is-point tie-point registration could shift the
  whole canon ~half a pixel (~5 m). Uniform shift cancels in gradients — verify once
  against a surveyed benchmark before canon publish.

**Clean in sweep 8:** balance transaction coordinator (string amounts, budget caps — no
float money); leaderboard sync service (verify-only, chain-authoritative; note its
hand-rolled byte parser must move in lockstep with any V4-B `VaultLeaderboard` layout
change); economics SQL types (NUMERIC throughout, bps-sum CHECK, rank 1–10 CHECK);
decompress (zip-bomb-safe); polyline codec (deliberate missing-elevation ranges);
tile_service (thin H3 wrapper); emergency controls (flags, no math); achievement
milestone-crossing logic; DEM bilinear interpolation; BoulderScan (display-only).

**Declared out of scope / accepted residual:** Discord bot (display client), web/org
(marketing), web/portal-legacy (dead), climb_lab (operator lab tool), road-attribution
naming percentages (display), tools/mcp-server (dev tooling), mobile (parked lane — 2026-04-16
audit stands). These carry no economic math.

## Sweep 9 — Ultra pass: mechanical verification + persistence deep-read (2026-07-09)

The tiers previously "sampled" are now read or machine-verified.

- **9.1 All 16 on-chain account SIZE constants mechanically verified.** Wrote
  `scripts/anchor_size_audit.py`: parses every `#[account]` struct in lib.rs, computes
  Borsh sizes, diffs against the hand-written SIZE expressions. Every one matches
  (Vault 617, ProgramConfig 325 across its 4-constant chain, DungMintState 121,
  BeetleCard 103, VaultStake 105, …). Whole class of rent/realloc/truncation bugs
  excluded by machine. Run it in CI after any lib.rs struct change.
- **9.2 Migration byte-surgery verified.** The raw `data[offset..]` writes
  (lib.rs:3955–4026) all derive offsets from the verified constant chain, match struct
  field order (= Borsh order), guard `data.len() >= SIZE`, and use LE consistently.
  `write_vault_counter_count` hits exactly [8..16]. Clean.
- **9.3 v2 signature terrain flag hardcoded to 0.** The live assembly passes
  `terrain_class = 0` ("flat") for every climb (`persistence.rs:822`) — the
  terrain-adaptive classification never reaches the signature. Second dead field inside
  checksummed identity bytes (with the direction bit, 4.4). Harmless to matching (flags
  aren't compared); one more reason signature bytes ≠ identity (canon-first confirmed).
- **9.4 Two gradients under one name inside the live engine.** `ClimbV2.avg_gradient_pct`
  is set to *boundary* (net-rise) gradient (`persistence.rs:780`), discarding
  `DisplaySegmentMetrics.avg_gradient_pct` (cumulative-ascent-based) computed two lines
  earlier. Consequences: (a) the live tribute intensity multiplier uses net gradient —
  *revises finding V3*: the live path is saner than the refinement-layer definition;
  (b) `ClimbV2.vert_m` = net rise, which **matches canon semantics** — *revises C3*: the
  cutover vert mismatch is confined to ride-total layers (Python ride_metrics, v1 sig),
  not the climb layer. Census updated.
- **9.5 Persistence deep-read complete (formerly "sampled").** Core persistent-homology
  filtration: textbook-correct (union-find sublevel, elder rule, deterministic
  tie-breaks). Boundary scorers (`reversed_pair_candidate_score`): corpus-weighted
  (×140/÷42/×80 magic constants) but deterministic, epsilon-tied to shorter span. The
  `− time_s/42` term concretely documents mechanism 4.6: window selection mildly favors
  faster-time boundaries, per ride. `trim_marginal_tails` / `merge_nearby_low_vert_fragments`:
  sound — quality-gain hysteresis, displayability re-checked after rebuild, pairwise-only
  merge per pass (conservative). No money-class bugs in the chain that produces
  record-board times; the residual risk is corpus-fit, not correctness.

## Notes / low severity

- Sensor-integrity GPS "teleportation" is distance-only between fixes (ignores Δt) —
  tunnels false-flag, slow spoofed drift passes (`sensor_integrity.py:192`). Use dist/Δt.
- `get_cal_balance` returns float display units — fine below ~9M CAL.
- kcal uses avg-nonzero-power × elapsed time (display-only overestimate).
- Display CAL `int(tss)` vs base `int(tss·1e9)` can disagree by <1 CAL.
- BeetleCard: CLAUDE.md gap-table row is stale — code is hybrid score-unlock + DUNG burn
  (25 × 2^(level−1), `lib.rs:896`). Frozen feature; doc fix.
- `vault_id == 0` init sentinels (legend/leaderboard) collide with legitimate vault 0 —
  harmless today; explicit `initialized` flag at V4-B.
- Record board as perpetual annuity is **intentional** (Tim, 2026-07-08) — add one
  sentence to PROTOCOL_TRUTHS so future reviewers don't re-flag it.

---

## Recommended attack order

**Superseded for execution by the dependency order in
`docs/design/MATH_AUDIT_PHASE2_2026-07-12.md`.** This table is retained as the first-pass
record.

| # | Item | Size | Lane |
|---|---|---|---|
| 1 | 1.1 gate record-board chain write on validation | S | backend |
| 2 | 1.2 geometry-gated economic matching (kill v1 fallback) | S | backend |
| 3 | 1.4 flow-meter tribute model (RATIFIED) — lifetime accumulator, weekly payout heartbeat; retroactive record-board entry; loud failures | M | backend+protocol |
| 4 | 1.3 server-derived FTP + IF/TSS caps | M | backend |
| 5 | 1.6 conserved tribute weights | S | backend |
| 6 | 2.1 epoch-time module (1972 dates) | S | backend |
| 7 | 2.6 CTL gap decay · 2.7 fail-loud import · 1.8 withdraw-all | S each | backend |
| 8 | 3.1 metrics consolidation (census closer) | M | backend+rust |
| 9 | 1.7 ledger NUMERIC + serialization | M | backend+db |
| 10 | Tier-3 canon fixes (C1–C7) while v0.1 is wet | M | canon epic |
| 11 | V4-B batch: 1.5 receipts, 2.2 tie-break, 2.3 eligibility, 2.8 units, 2.9 crank hardening, sentinel flags | L | protocol **[ratify 1.5/2.2/2.3]** |
| 12 | 2.5 auto-halving + emission copy | S | protocol **[ratify]** |
| 13 | Promote settlement sim to property test in `tests/` | S | backend |
| 14 | 8.1 supply-state projection writer (revive the dead gauge) + 8.2 gauge honesty | S | indexer+portal |
| 15 | 8.4 drop points-era SQL functions · 7.1 chain_rejected marking · P4/2.7 fail-loud batch | S each | backend |
| 16 | Wire `scripts/anchor_size_audit.py` into pre-commit/CI (lib.rs struct guard) | S | tooling |

*Compiled by Claude (Fable) across audit sweeps 1–9, 2026-07-08/09. Sources: direct code
reading at cited file:line + simulation. `boulderroller-v2-rbvd` has since landed; see the
Phase 2 addendum for current status.*
