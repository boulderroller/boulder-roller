# Climb Detection v2: Implementation Plan

*February 2026*

**Status:** HISTORICAL — earlier detector implementation plan
**Scope:** Alpha (10-50 riders, 1-3 metro areas)
**Prereqs:** `docs/CLIMB_DETECTION_V2_SPEC.md` (design), `docs/OPEN_PROBLEMS.md` (gaps), `history/CLIMB_DETECTION_OPEN_PROBLEMS_SOLUTIONS_2026-02-24.md` (decisions)

Current canon-first identity and the detector freeze are governed by [PROTOCOL_TRUTHS.md](PROTOCOL_TRUTHS.md) and [FRESHEST_SPEC.md](FRESHEST_SPEC.md), with existing detector parameters in [DETECTOR_PARAMS.md](DETECTOR_PARAMS.md).

---

## Relationship to Baseline Decisions

The approved baseline (`history/CLIMB_DETECTION_OPEN_PROBLEMS_SOLUTIONS_2026-02-24.md`) defines the **target architecture**. This plan implements the **alpha subset** — what's needed to ship a noticeably better climb experience for 10-50 riders. Two baseline decisions are intentionally deferred:

| Baseline Decision | This Plan | Rationale | Revisit Trigger |
|-------------------|-----------|-----------|-----------------|
| DEM-anchored drift correction before persistence | Deferred — run persistence on raw baro | At alpha scale (1-3 cities, same weather patterns), barometric drift has minimal impact on matching. Adding DEM lookup to the ride-time hot path is premature complexity. | Data shows drift causing matching failures across weather conditions |
| BIC changepoint boundary segmentation for effort bounds | Deferred — reuse existing gradient-walk trim | The existing `trim_climb_segment` already removes flat lead-in and produces reasonable effort bounds. BIC adds implementation complexity for marginal UX improvement at alpha. | User complaints about climb start/end points |

These deferrals are scope decisions, not disagreements with the baseline. The baseline is correct for production scale; this plan gets us to production scale.

---

## Premise

The v1 detector works but has 90 hand-tuned parameters across 5 terrain presets, broken SHA256 signature similarity, and no geographic significance scoring. The goal is to ship persistence-based detection that delivers a noticeably better climb experience for alpha riders — not to build a globally-scaled terrain intelligence platform.

---

## Existing Infrastructure (Don't Rebuild)

These components are working and should be extended, not replaced:

| Component | File | Lines | What It Does |
|-----------|------|-------|-------------|
| Climb cards | `web/portal/src/components/ride/ClimbsTable.tsx` | 1009 | Category, name, vault match, KOM, PR, VAM, expandable detail |
| Elevation profile | `web/portal/src/components/ride/ElevationChart.tsx` | 562 | Canvas-based, gradient coloring, climb shading, rubber-band select |
| Map overlay | `web/portal/src/components/ride/GradientClimbOverlay.tsx` | — | Gradient-colored polylines on route map |
| Road names | `backend/app/services/tile_service.py` (TileAttributionService) | ~180 | OSM road name attribution for climbs |
| Boundary trim | `workout-parse/src/climb/detector.rs` (trim_climb_segment) | ~40 | Gradient-walk inward from endpoints, removes flat lead-in |
| UCI categories | `workout-parse/src/climb/types.rs` (calculate_uci_category) | ~20 | HC/1/2/3/4/UC from gain, gradient, distance |
| Signature guard | Retired at V4-B canon cutover | — | Historical detector signatures are discovery-only; D12 commitment and Climb-to-Vault binding tests protect economic identity |

---

## Phase 0: Validation Dataset

**Dependencies:** None
**Deliverable:** `tests/validation/` directory with ride files and ground-truth manifest

### Work

1. Collect 20-30 real FIT files from the team covering at least 3 terrain types (flat, rolling, mountainous/hilly).
2. Manually annotate ground-truth climbs per file: approximate timestamps, approximate vert, name if known.
3. Store annotations in a manifest JSON:
   ```json
   {
     "file": "philly_manayunk_loop.fit",
     "terrain": "urban_hills",
     "expected_climbs": [
       { "name": "Manayunk Wall", "approx_vert_m": 65, "approx_start_s": 1200 }
     ]
   }
   ```
4. Run v1 detector on all files, record results as baseline (detected climbs, boundaries, categories, signatures).

### Validation

Baseline established. Every subsequent phase measures against this.

---

## Phase 1: Persistence Engine

**Dependencies:** Phase 0 (ride files for testing)
**Deliverable:** `persistence.rs` producing correct climb features, shadow-running alongside v1

### Work

1. **New file** `workout-parse/src/climb/persistence.rs`:
   - Union-find with path compression + union by rank.
   - Process samples in elevation-sorted order (sublevel-set filtration).
   - Elder Rule: younger component (higher birth) dies at merge point.
   - Merge tree construction (parent-child nesting).
   - Essential class emission (global min to global max).
   - Noise gate: discard pairs with persistence < 3.0m.
   - ~200-250 lines with tests.

2. **New struct** alongside existing `ClimbPattern`:
   ```rust
   pub struct ClimbV2 {
       // Topological (canonical) — used for matching, economics
       pub birth_idx: usize,
       pub death_idx: usize,
       pub birth_elev: f64,
       pub death_elev: f64,
       pub persistence: f64,
       pub is_essential: bool,
       pub sub_climbs: Vec<ClimbV2>,

       // Effort (display) — used for UI, uses existing gradient-walk trim
       pub effort_start_idx: usize,
       pub effort_end_idx: usize,

       // Enriched metrics (same as existing ClimbPattern fields)
       pub vert_m: f64,
       pub time_s: u32,
       pub distance_m: f64,
       pub avg_gradient_pct: f64,
       pub avg_power_w: Option<f64>,
       pub avg_hr: Option<u8>,
       pub tile_ids: Vec<String>,

       // Significance (filled by Phase 3, None until then)
       pub significance: Option<SignificanceScore>,

       // Signatures (filled by Phase 2, None until then)
       pub signature_v1_hex: Option<String>,
       pub signature_v2_hex: Option<String>,
   }
   ```

3. **Effort boundaries** from existing gradient-walk trim logic (reuse `trim_climb_segment` approach within canonical bounds). No changepoint segmentation — the existing method works.

4. **New PyO3 function** `detect_climbs_v2()` in `lib.rs`:
   - Takes same inputs as existing `detect_climbs_adaptive()`.
   - Returns both v1 and v2 results for comparison.
   - v2 results include persistence pairs, merge tree structure, and effort-trimmed boundaries.

5. **Schema migration** for v2 climb fields on `patterns_climb`:
   ```sql
   ALTER TABLE patterns_climb ADD COLUMN detection_version INT DEFAULT 1;
   ALTER TABLE patterns_climb ADD COLUMN persistence_m REAL;
   ALTER TABLE patterns_climb ADD COLUMN canonical_start_offset_s INT;
   ALTER TABLE patterns_climb ADD COLUMN canonical_end_offset_s INT;
   ALTER TABLE patterns_climb ADD COLUMN birth_elev_m REAL;
   ALTER TABLE patterns_climb ADD COLUMN death_elev_m REAL;
   ALTER TABLE patterns_climb ADD COLUMN is_essential BOOLEAN;
   ALTER TABLE patterns_climb ADD COLUMN merge_parent_id UUID;
   -- FK with same-activity constraint (enforced at application level, not DB FK):
   -- merge_parent_id references patterns_climb(id) WHERE parent.activity_id = child.activity_id.
   -- DB-level FK omitted because cross-activity constraint can't be expressed in a simple FK.
   -- Application enforces: parent must exist, must share activity_id, must be inserted before child.
   ALTER TABLE patterns_climb ADD COLUMN signature_v2_hex TEXT;
   ALTER TABLE patterns_climb ADD COLUMN significance_g REAL;
   ALTER TABLE patterns_climb ADD COLUMN significance_percentile REAL;
   ALTER TABLE patterns_climb ADD COLUMN significance_return_period REAL;
   ALTER TABLE patterns_climb ADD COLUMN significance_confidence_tier INT;
   ALTER TABLE patterns_climb ADD COLUMN significance_bootstrapped BOOLEAN DEFAULT FALSE;
   ```

6. **Update backend model** `backend/app/models/patterns.py`:
   - Add corresponding fields to `ClimbPattern` dataclass.
   - Update `to_dict()` to include v2 fields when present.

7. **Update pattern repository** `backend/app/repositories/pattern.py`:
   - Add v2 fields to `store_climb_pattern()` insert payload.
   - v2 fields are nullable — v1-detected climbs continue to work unchanged.
   - **Merge-tree insertion order:** When storing climbs with parent-child nesting, insert in topological order (parents before children). The persistence engine emits climbs sorted by persistence descending, so essential/parent climbs come first naturally. `store_climb_pattern()` returns the inserted row's `id`, which the caller passes as `merge_parent_id` for child climbs. Application code validates `merge_parent_id` shares the same `activity_id` before insert.

8. **Shadow-run** in `backend/app/services/pattern_engine.py`:
   - Call `detect_climbs_v2()` on every ride.
   - Log v2 results alongside v1.
   - Do NOT use v2 for vault matching yet.
   - **Storage strategy (no duplicate rows):** v1 detection produces the canonical `patterns_climb` row as before (`detection_version=1`). v2 shadow results populate the v2-specific columns (`persistence_m`, `canonical_start_offset_s`, `canonical_end_offset_s`, `birth_elev_m`, `death_elev_m`) on the **same row** via UPDATE after v1 insert. This ensures the read path (`get_patterns_for_activity`) always returns exactly one row per climb — no duplicate-climb risk in the UI.
   - **v2-to-v1 pairing rule:** When a ride has multiple climbs, pair each v2 detection to the v1 row with the greatest time overlap. Overlap = `min(v1.end_offset_s, v2.effort_end_offset_s) - max(v1.start_offset_s, v2.effort_start_offset_s)`. Highest overlap wins, greedy (each v1 row matched at most once). Ties broken by earlier `start_offset_s`; minimum overlap threshold of 30s (below that, treat as unmatched). Unmatched v2 detections go to `climb_shadow_log` as `v2_only`.
   - The `detection_version` column flips from 1 → 2 only at Phase 5 cutover, when v2 becomes the authoritative detector for effort boundaries.
   - v2-only detections (climbs v2 finds but v1 misses) are logged to a separate `climb_shadow_log` table for analysis, NOT inserted into `patterns_climb` during shadow mode. These appear in the comparison metrics but never reach the user. Schema:
     ```sql
     CREATE TABLE climb_shadow_log (
         id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
         activity_id UUID NOT NULL REFERENCES rides(id),
         detection_version INT NOT NULL DEFAULT 2,
         persistence_m REAL,
         birth_elev_m REAL,
         death_elev_m REAL,
         effort_start_offset_s INT,
         effort_end_offset_s INT,
         vert_m REAL,
         matched_v1_pattern_id UUID,  -- NULL for v2-only detections
         log_type TEXT NOT NULL,       -- 'v2_only' | 'v2_metrics'
         metrics_json JSONB,           -- comparison stats (boundary delta, etc.)
         created_at TIMESTAMPTZ DEFAULT now()
     );
     ```

### Validation

- v2 recall >= v1 on the 20-30 ride dataset.
- v2 finds every climb v1 finds.
- v2 shows reduced false positives on mixed-terrain rides (the discrete classification gap).
- Processing latency within 2x of v1 (persistence is O(n), should be faster than momentum model).

---

## Phase 2: DCT Signatures

**Dependencies:** Phase 1 (persistence produces climb segments to fingerprint)
**Deliverable:** v2 signatures generated alongside v1, multi-gate matching operational

### Work

1. **Add dependencies** to `workout-parse/Cargo.toml`:
   - `half = "2.x"` (f16 support)
   - `blake3 = "1.x"` (checksum)

2. **New file** `workout-parse/src/climb/signature_v2.rs`:
   - DCT-II transform on 32-bin gradient profile (same binning as v1).
   - Keep first 16 coefficients, pack as f16.
   - 64-byte layout: version(1) + flags(1) + vert(2) + dist(2) + grad(2) + h3_anchor(8) + dct_f16[16](32) + blake3(16).
   - Relative Euclidean distance metric: `d_rel = ||c_x - c_y||_2 / (0.5 * (||c_x||_2 + ||c_y||_2))`.
   - Multi-gate matching: version check → H3 proximity (k-ring 3) → geometric pre-filter (vert/dist within 15%) → DCT distance < 0.08.
   - Match result enum: `Match` / `ProbableMatch` / `NoMatch` / `Incompatible`.

3. **Do not touch `signature.rs`.** The pre-commit hook protects v1 signatures. v2 is a separate code path.

   **Signature stability test** (supplements the local `.claude/hooks/` guard with a CI-enforceable check):
   - Add `#[test] fn test_v1_signature_deterministic()` in `signature.rs` that generates a signature from a known elevation/timestamp sequence and asserts the output hex matches a pinned expected value.
   - This test runs in `cargo test` and CI, not just as a local Claude hook.
   - If the test breaks, it means someone changed v1 signature generation, which would corrupt all existing vault matches.

4. **Schema migration:**
   ```sql
   ALTER TABLE indexed_vaults ADD COLUMN signature_version INT DEFAULT 1;
   ALTER TABLE indexed_vaults ADD COLUMN signature_v2_hex CHAR(128);
   ```

5. **Update Python-side signature handling** for dual-version support:

   **Version discrimination:** v1 signatures have NO version byte — bytes 0-31 are raw SHA256 output, so byte 0 is arbitrary. v2 signatures have an explicit version byte (0x02) at position 0. **Do not use byte-sniffing to distinguish versions.** Instead, the column determines the version: `signature_hex` is always v1, `signature_v2_hex` is always v2. The version byte in v2 is for forward compatibility (v3+), not for v1 discrimination.

   - **`backend/app/services/patterns/climb_signature.py`** — Add `ClimbSignatureV2` class alongside existing `ClimbSignature`. No version-aware factory on raw hex. Each class is constructed explicitly from its respective column. Both implement `similarity(other)` but: v1 uses Hamming distance on SHA256 bits (existing), v2 uses relative Euclidean distance on DCT coefficients. Cross-version `similarity()` returns 0.0 (incompatible).

   - **`backend/app/services/vault_indexer.py`** — `IndexedVault` dataclass (line 48): add `signature_v2_hex` field and `signature_v2` property that constructs a `ClimbSignatureV2` when present. `VaultSignatureCache.find_matches()` (line 276): if both ride and vault have v2 signatures, use v2 multi-gate match (H3 proximity → geometric → DCT distance). Otherwise fall back to v1 `similarity()`. Cache `load()` reads both columns.

   - **`backend/app/repositories/vault.py`** — `find_vaults_by_signature_similarity()` (line 263): the current implementation parses v1 signature bytes at fixed offsets (32-36 for vert, etc.). Keep this for v1 lookups. Add a separate v2 lookup path that uses `ClimbSignatureV2` methods. Caller passes version hint based on which column is populated.

   - **`backend/app/services/climb_vault.py`** — `match_climb_pattern()` currently calls `ClimbSignature.similarity()`. Update to check if both sides have v2 signatures first; if so, use `ClimbSignatureV2.similarity()`. Tile overlap boost logic stays the same.

6. **Dual generation:** During ride processing, generate both v1 and v2 signatures. Store both in `patterns_climb` (`signature_hex` for v1, `signature_v2_hex` for v2). Match against both during vault lookup. v2 match takes precedence when both vaults have v2 signatures.

### Validation

- On the 20-30 ride dataset, measure separation gap between same-climb matches and different-climb non-matches.
- Target: gap > 2x (spec predicts 2.3x from Monte Carlo, real GPS will degrade this).
- Same-climb recordings from different days/conditions should match via v2 where v1 fails (because SHA256 avalanches on minor gradient differences).

---

## Phase 3: Minimal GPD Bootstrap

**Dependencies:** Phase 1 (bootstrap uses persistence on DEM road profiles via PyO3)
**Deliverable:** GPD parameters for alpha rider areas, significance scoring operational

### Work

1. **Download FABDEM tiles** for alpha rider areas only. Identify which H3 res-5 cells our riders are in (query `wallet_tile_history`), download the corresponding FABDEM 1-degree tiles. Probably 5-20 tiles.

2. **New module** `backend/app/services/terrain_bootstrap.py`:
   - For each target H3 res-5 cell:
     - Extract OSM road polylines within the cell (via Overpass API or pre-downloaded extract).
     - Sample FABDEM elevation along road polylines (bilinear interpolation at ~30m spacing).
     - Run 0D persistence via PyO3 `compute_persistence()` on each road segment.
     - Collect all persistence values above 3.0m noise floor.
     - Adaptive threshold selection: search quantiles 0.80-0.95 for parameter stability.
     - Fit GPD via PWM (L-moments). ~20 lines of numpy.
     - Compute confidence tier, score cap, diagnostics.
   - For parent H3 res-4 cells: aggregate child cell data for coarse prior (used as fallback).

3. **New table** `terrain_cells`:
   ```sql
   CREATE TABLE terrain_cells (
       h3_index TEXT PRIMARY KEY,        -- TEXT, not BIGINT (consistent with tile pipeline)
       h3_resolution INT NOT NULL,
       n_features INT,
       k_exceedances INT,
       threshold_m REAL,
       threshold_quantile REAL,
       gpd_xi REAL,
       gpd_sigma REAL,
       xi_ci_hi REAL,
       g_cap REAL,
       confidence_tier INT,
       tail_diag_pass BOOLEAN,
       bootstrapped_at TIMESTAMPTZ,
       osm_road_km REAL,
       parent_h3_index TEXT              -- TEXT, matches h3_index type
   );
   ```
   **Note:** H3 indices are stored as TEXT strings throughout the existing tile pipeline (`activity_tile_samples.tile_id`, `wallet_tile_history.tile_id`, etc.). Using TEXT here avoids conversion/overflow bugs and keeps lookups consistent. The h3o Rust crate and Python h3 library both emit string representations natively.

4. **Significance scoring function** in `terrain_bootstrap.py`:
   - Input: climb persistence value + H3 cell of climb midpoint.
   - Lookup precedence (strict order):
     1. **Res-5 cell fit** → use directly if available and confidence tier >= 2.
     2. **Parent res-4 cell fit** → use as fallback with `confidence_tier` reduced by 1 and `bootstrapped=false` flag.
     3. **Neither exists** → return `None`. Frontend shows UCI category only (already implemented). API response includes `significance_bootstrapped: false`.
   - Compute G_conservative per spec (section 5.6).
   - Return `SignificanceResult`: g_score, g_point, g_uncertainty, confidence_tier, bootstrapped flag, source_resolution.

5. **Write-back to `patterns_climb`:** After significance scoring, UPDATE the climb row's `significance_g`, `significance_percentile`, `significance_return_period`, `significance_confidence_tier`, `significance_bootstrapped` columns. This runs in `ride_processor.py` after Phase 1 shadow-run and after `terrain_bootstrap.score_climb()` returns. Idempotent: re-processing a ride overwrites significance columns (latest GPD fit wins). Rides processed before Phase 3 have NULL significance — backfill by re-running significance scoring on existing `patterns_climb` rows that have non-null `persistence_m`.

### Validation

- Spot-check: a notable climb in a flat cell scores higher than the same-sized climb in a mountainous cell.
- The ξ shape parameter matches intuition: positive in mountainous cells, near-zero in rolling, negative in flat.
- Scores are conservative (G_conservative <= G_point).

---

## Phase 4: Frontend Integration

**Dependencies:** Phase 3 (significance scores in API), Phase 1 schema migration (v2 columns exist)
**Deliverable:** Users see significance alongside existing climb data

### Work

1. **Update rides route** `backend/app/routes/rides.py` (line ~575):
   - Add camelCase mappings for v2 fields: `significanceG`, `localPercentile`, `localReturnPeriod`, `significanceBootstrapped`, `confidenceTier`, `persistenceM`, `canonicalStartOffsetS`, `canonicalEndOffsetS`, `isEssential`.
   - These fields come from `patterns_climb` (populated during Phase 1 shadow-run and Phase 3 scoring).
   - Include v2 fields whenever they are **non-null**, regardless of `detection_version`. The v2 columns (significance, persistence, canonical bounds) are enrichment data populated during shadow mode — they don't depend on v2 being the authoritative detector. `detection_version` controls which detector owns effort boundaries, not whether enrichment is shown.
   - Extended API response per climb:
   ```json
   {
     "significanceG": 0.52,
     "localPercentile": 92,
     "localReturnPeriod": 125,
     "significanceBootstrapped": true,
     "confidenceTier": "moderate",
     "persistenceM": 47.2,
     "canonicalStartOffsetS": 1180,
     "canonicalEndOffsetS": 1520,
     "isEssential": false
   }
   ```

2. **Update `ClimbsTable.tsx`** — add significance display beneath existing category badge:
   - If bootstrapped: "Top 8% locally" or "1 in 125 climbs here"
   - If not bootstrapped: show nothing (UCI category is already displayed)
   - Subtle confidence indicator for low-confidence cells

3. **Dual boundary display:**
   - Default (effort boundaries): distance, avg gradient, time shown for the gradient-trimmed segment (existing `start_offset_s`/`end_offset_s`).
   - Detail expansion: show canonical boundaries (`canonical_start_offset_s`/`canonical_end_offset_s`), persistence value, merge tree parent if nested.

4. **Verify road name attribution** works for v2-detected climbs. The climb boundaries may differ slightly from v1, which could shift which road segments are attributed. Test with real rides.

### Validation

- Show updated climb cards to 3-5 cyclists. Does "Cat 3 — Top 8% locally" make sense without explanation?
- If they ask "top 8% of what?" the copy needs work.
- If they say "that feels right for this area" we're good.

---

## Phase 5: Cutover

**Dependencies:** Enough rides through shadow mode to be confident (target: 100+ rides)
**Deliverable:** v2 is primary detection path

### Work

1. Run full v1/v2 comparison across all accumulated alpha ride data.
2. Quality gates:
   - v2 recall >= v1 baseline.
   - False positive reduction on mixed-terrain rides.
   - Vault matching stability: same-climb match rate improved or equal.
   - Processing latency: no more than 2x v1 per ride.
3. Promote v2 to primary in `pattern_engine.py`.
4. Switch vault matching to v2 multi-gate pipeline. Keep v1 signature fallback for vaults that only have v1 signatures.
5. Keep v1 code in repo. Remove from hot path. Available for forensic replay via config flag.
6. Update `detect_climbs_adaptive()` PyO3 function to call v2 internally (preserving API compatibility).

### Validation

- No regression reports from alpha riders after cutover.
- Monitor vault matching rates for 1 week post-cutover.

---

## Explicitly Deferred

| Item | Reason | Revisit When |
|------|--------|-------------|
| Elevation correction (DEM drift removal) | Requires DEM at ride time, invisible impact at alpha scale | Data shows drift is causing matching failures |
| BIC changepoint boundary segmentation | Existing gradient-walk trim is sufficient | User complaints about climb start/end points |
| Global FABDEM bootstrap | 12 TB raw tiles for 10-50 riders in 1-3 cities | Ridership expands beyond initial metro areas |
| Vault discovery map | 5-20 vaults at alpha, not enough density | 100+ vaults in a metro area |
| Deep leaderboard (full rank) | Separate product feature, not detection-related | Dedicated product sprint |
| Comparative ride view | Needs historical data that doesn't exist yet | Users have 10+ completions of same vault |
| Live segments / head unit | Requires Garmin/Wahoo partnerships | Post-TGE with dedicated partnership effort |
| Descent / sprint detection | Scope discipline, climbs are core primitive | After v2 climbs are validated and stable |

---

## Dependency Graph

```
Phase 0 (Validation Dataset)
    │
    ├──→ Phase 1 (Persistence Engine)
    │        │
    │        ├──→ Phase 2 (DCT Signatures)
    │        │        │
    │        │        └──→ Phase 5 (Cutover)
    │        │                 ↑
    │        └──→ Phase 3 (GPD Bootstrap)
    │                 │
    │                 └──→ Phase 4 (Frontend Integration)
    │                          │
    │                          └──→ Phase 5 (Cutover)
```

Phases 2 and 3 can run in parallel after Phase 1 completes.
Phase 5 requires all prior phases.

---

## Key Files Touched Per Phase

| Phase | New Files | Modified Files |
|-------|-----------|---------------|
| 0 | `tests/validation/*.fit`, `tests/validation/manifest.json` | — |
| 1 | `workout-parse/src/climb/persistence.rs`, migration SQL (v2 columns on `patterns_climb`, `climb_shadow_log`) | `types.rs`, `mod.rs`, `lib.rs`, `pattern_engine.py`, `models/patterns.py`, `repositories/pattern.py` |
| 2 | `workout-parse/src/climb/signature_v2.rs`, migration SQL (`indexed_vaults` v2 columns) | `Cargo.toml`, `mod.rs`, `lib.rs`, `vault_indexer.py`, `patterns/climb_signature.py`, `repositories/vault.py`, `signature.rs` (test only) |
| 3 | `backend/app/services/terrain_bootstrap.py`, migration SQL (`terrain_cells`) | `pattern_engine.py`, `ride_processor.py` |
| 4 | — | `ClimbsTable.tsx`, `routes/rides.py` |
| 5 | — | `pattern_engine.py`, `lib.rs` |
