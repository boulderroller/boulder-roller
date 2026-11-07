# Benchmark Program v1

**Status:** DRAFT
**Last updated:** 2026-02-27

This document defines the formal benchmark program for the Boulder Rollers
climb detection system. Every algorithm change MUST be evaluated against
this benchmark before merge.

---

## Principles

1. **Fixed splits.** Benchmark data does not change between runs.
2. **Scorecards, not eyeballs.** Every run produces machine-comparable metrics.
3. **Drift detection.** Regressions are caught automatically, not discovered in production.
4. **Adversarial coverage.** The benchmark includes cases designed to break the detector.

---

## Benchmark Tiers

### Tier 1: Synthetic Ground Truth (runs in CI, < 30s)

**Location:** `tests/validation/test_synthetic_ground_truth.py`
**Runner:** `pytest tests/validation/ -v`

Purpose: Verify mathematical invariants and boundary conditions with
constructed elevation profiles where the correct answer is known exactly.

| Suite | Tests | What it covers |
|-------|-------|----------------|
| TestPersistenceDetection | 15 | Noise gate, merge pairs, bounds validity |
| TestFullDetection | 6 | End-to-end climb detection, flat/descent negatives |
| TestGPDFitting | 7 | GPD parameter estimation stability |
| TestDiversityMetrics | 5 | Kish N, confidence tiers |
| TestScoringPipeline | 9 | GPD scoring bounded, monotonic, terrain-differentiating |
| TestFullPipeline | 4 | Persistence + significance integration |

**Pass criteria:** 100% pass. Any failure blocks merge.

### Tier 2: Fixture Regression (runs in CI, < 60s)

**Location:** `tests/validation/` (8 FIT files + manifest.json)
**Runner:** `pytest tests/validation/test_synthetic_ground_truth.py::TestRegressionBaseline -v`

Purpose: Verify detection on real ride files against hand-curated
ground truth (21 expected climbs across 8 files).

| File | Terrain | Expected climbs | Key assertion |
|------|---------|-----------------|---------------|
| Afternoon_Ride (1).fit | flat | 0 | **Negative control** — no false positives |
| t_h_e_w_a_l_l.fit | urban_hills | 1+ (45-80m) | Manayunk Wall detected |
| Morning_Ride (1).fit | mountainous | 2+ (>=50m) | Mt. Lemmon gold standard |
| Afternoon_Ride.fit | rolling | 2+ (>=15m) | Rolling terrain rollers |
| in_the_bag_.fit | rolling | 1+ (>=60m) | Manayunk/Roxborough ridge |
| 05_07_2015_*.fit | hilly | varies | GPS sentinel handling |
| Lunch_Ride.fit | hilly | varies | Western suburbs |
| Morning_Ride.fit | hilly | varies | Long ride stability |

**Stability check:** Climb counts must fall within expected ranges
(defined in `test_climb_count_stability`). Ranges are NOT tight —
they catch catastrophic regressions, not minor tuning.

**Pass criteria:** All assertions pass. Ranges updated only with
signed change note.

### Tier 3: Corpus Benchmark (runs manually, ~5 min)

**Location:** `tools/corpus/corpus.db` (frozen snapshot)
**Runner:** `tools/corpus/benchmark.py` (to be created)

Purpose: Full-scale regression against 2,893 rides / 46,758 v2 climbs.
Produces a scorecard that must be reviewed for any algorithm change.

**Scorecard metrics:**

```
DETECTION METRICS
  total_climbs:           int    # Total climbs detected
  significant_climbs:     int    # Climbs >= 20m persistence
  essential_pct:          float  # % marked essential
  median_vert_m:          float  # Median vertical gain
  p95_vert_m:             float  # 95th percentile vert
  zero_distance_count:    int    # MUST be 0
  impossible_vam_count:   int    # MUST be 0
  sub_5m_count:           int    # MUST be 0
  max_climbs_per_ride:    int    # Ceiling check

SIGNATURE METRICS
  unique_v2_signatures:   int    # Total unique DCT signatures
  signature_coverage_pct: float  # % of significant climbs with v2 sig

MATCHING METRICS (cross-geokey fuzzy)
  exact_geokey_vaults:    int    # Vaults from exact signature match
  fuzzy_gps_vaults:       int    # Vaults from GPS-gated fuzzy match
  total_completions:      int    # Rides touching any vault
  false_positive_pct:     float  # Estimated from GPS > 600m checks

TERRAIN DISTRIBUTION
  flat_rides:             int
  rolling_rides:          int
  hilly_rides:            int
  mountainous_rides:      int
```

**Drift detection:** Scorecard is compared to the previous run's scorecard.
Any delta is reported. Deltas > 5% on any metric require justification.

**Pass criteria:** Manual review. Quality gates (zero impossible VAM,
zero sub-5m climbs) are hard failures.

### Tier 4: Adversarial Suite (runs manually, on demand)

**Location:** `tests/validation/adversarial/` (to be created)
**Purpose:** Cases designed to break the detector.

| Category | Test cases | What it catches |
|----------|-----------|-----------------|
| GPS sentinel flood | FIT with INT32_MIN lat/lon | Sentinel leaking into distances |
| Long pause (8 hrs) | Ride with overnight pause mid-climb | Giant fake climb from time gap |
| Barometric spike | 500m elevation jump for 1 sample | Single-sample spike in profile |
| Sparse points | 1 sample per 30s (phone GPS) | Distance inflation from interpolation |
| Zero elevation | All elevation_m = 0 | Division by zero, gradient NaN |
| Null power | No power data at all | w_per_kg crash |
| Duplicate timestamps | Multiple samples at t=0 | Time delta = 0 division |
| Max duration | 48h + 1s activity | Duration guard boundary |
| Micro climb spam | 100 x 3m oscillations | Noise gate overwhelmed |
| Single massive climb | 3000m continuous gain | Vert overflow in u16 signature field |

**Pass criteria:** No crash, no panic, no NaN in output. Detector may
produce 0 climbs (correct abstention) or reasonable climbs. Never garbage.

---

## Benchmark Data Provenance

### Frozen datasets

| Dataset | Location | Version | Frozen date |
|---------|----------|---------|-------------|
| Validation fixtures | `tests/validation/*.fit` | v1 | 2026-02-24 |
| Ground truth manifest | `tests/validation/manifest.json` | v1 | 2026-02-24 |
| Corpus snapshot | `tools/corpus/corpus.db` | v2 post-quality-filters | 2026-02-25 |
| Pre-filter corpus | `tools/corpus/corpus_pre_quality_filters.db` | v2 pre-QF | 2026-02-24 |

### Data rules

1. Frozen datasets are NEVER modified in place. Create a new version.
2. Every dataset version is tagged with the detector version that produced it.
3. Raw Strava FIT files live outside the repo (privacy). Only curated
   fixtures and pre-processed databases are checked in.

---

## Running the Benchmark

### Quick (CI)
```bash
cd backend && source venv/bin/activate
pytest tests/validation/ -v
```

### Full (manual)
```bash
# Rebuild Rust module
cd workout-parse && cargo build --release && maturin develop

# Run Tier 1+2
cd ../backend && pytest tests/validation/ -v

# Run Tier 3 scorecard
cd ../tools/corpus && python benchmark.py --compare-to previous_scorecard.json

# Run Tier 4 adversarial (when suite exists)
cd ../../backend && pytest tests/validation/adversarial/ -v
```

---

## Scorecard Format

Every benchmark run produces a JSON scorecard:

```json
{
  "version": "benchmark-v1",
  "timestamp": "2026-02-27T12:00:00Z",
  "detector": "persistence",
  "workout_parse_version": "0.1.0",
  "commit": "abc1234",
  "tiers": {
    "synthetic": { "passed": 46, "failed": 0, "skipped": 0 },
    "fixture_regression": { "passed": 7, "failed": 0 },
    "corpus": { ... scorecard metrics ... }
  },
  "delta_from_previous": {
    "total_climbs": "+0 (0.00%)",
    "significant_climbs": "+0 (0.00%)",
    ...
  }
}
```

---

## Open Items

1. ~~**Create `tools/corpus/benchmark.py`**~~ — DONE. Scorecard generator with
   quality gates, delta comparison, drift detection. Auto-saves to `tools/corpus/scorecards/`.
2. ~~**Create adversarial test suite**~~ — DONE. 26 tests across 11 categories
   in `tests/validation/adversarial/test_adversarial.py`. Tests both detector
   and sensor integrity layer against degenerate inputs.
3. ~~**Fix climb-regression hook**~~ — DONE. Points at `tests/validation/`,
   uses `.claude/climb-baseline.json`.
4. ~~**Retire detector signature-stability hook at V4-B cutover**~~ — DONE.
   Detector signatures now feed discovery only; Vault identity is covered by
   the shared D12 canon commitment vector and Climb-to-Vault binding gates.
5. **CI integration** — Run Tier 1+2 on every push.
6. **Hard negative suite** — Same-H3-cell but different-climb pairs from corpus
   (we identified 58 false positives in the GPS analysis — these are gold).
