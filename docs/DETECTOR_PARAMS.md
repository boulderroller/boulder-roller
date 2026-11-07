# Canonical Detector Parameters

> **This file is the single source of truth for all climb detector tunable constants.**
> All other docs, sweep scripts, and comments should reference this file
> rather than hardcoding parameter values.
>
> A pre-commit hook warns when changes to `backend/app/services/patterns/climb.py`
> are not accompanied by an update to this file; it does not block the commit
> (`scripts/hooks/detector-param-guard.sh:51–71`).
>
> **Source code:** `backend/app/services/patterns/climb.py`
> **Algorithm:** `canonical_v2` (momentum + persistence fusion with corroboration scoring)
> **Last verified:** 2026-05-02

---

## Core Scoring

| Parameter | Value | Code Reference |
|-----------|-------|----------------|
| `CANONICAL_V2_MIN_SCORE` | 2.25 | climb.py:1759 |
| `CANONICAL_V2_SINGLE_SOURCE_PENALTY` | 0.75 | climb.py:1760 |
| Sparse sampling threshold adder | +0.5 | climb.py:2282 |
| Degraded elevation + low vert (<35m) adder | +0.25 | climb.py:2283-2284 |

---

## Heuristic Functions

### H2 — Power Confirmation (`_h2_power_confirmation_bonus`)
**Range:** [-1.0, +1.5]

Compares climb average power to ride average power. Confirms or contradicts
GPS/elevation-based detection with physiological data.

| Power Ratio (climb/ride) | Bonus |
|--------------------------|-------|
| >= 1.50 | +1.5 |
| >= 1.30 | +1.0 |
| >= 1.15 | +0.5 |
| >= 0.90 | 0.0 |
| >= 0.70 | -0.5 |
| < 0.70 | -1.0 |
| No power data | 0.0 |

### H3 — Terrain Context (`_h3_terrain_context_bonus`)
**Range:** [-3.0, +3.0]

Rescales climb significance relative to ride terrain classification.

**Notable Vert Thresholds (by terrain):**

| Terrain | Notable Vert | Notable Gradient |
|---------|-------------|-----------------|
| flat | 15m | 2.0% |
| rolling | 25m | 3.0% |
| hilly | 40m | 4.0% |
| mountainous | 80m | 5.0% |

**H3V multiplier:** 2.0x notable_vert = standout (+2.0 bonus)

### H4 — Intensity Score (`_h4_intensity_bonus`)
**Range:** [0, +3.0]

Uses `distance_m * gradient_pct^2` as intensity metric.

| Intensity Tier | Threshold | Bonus |
|---------------|-----------|-------|
| Top | >= 50,000 | +2.0 |
| High | >= 20,000 | +1.0 |
| Moderate | >= 8,000 | +0.5 |

**Steep punch bonus:** gradient >= 10% and 30-300s → +1.0; gradient >= 7% and 60-600s → +0.5

### H9 — Roller Filter (`_h9_roller_filter_bonus`)
**Range:** [-2.0, 0]

Penalizes short-duration low-gradient efforts (rollers, not climbs).

| Duration | Condition | Penalty |
|----------|-----------|---------|
| < 90s | gradient >= 12% | 0.0 (steep punch, allow) |
| < 90s | gradient >= 8% | -0.5 |
| < 90s | gradient < 8% | -2.0 (roller) |
| 90-180s | gradient >= 6% | 0.0 |
| 90-180s | gradient >= 4% | -0.5 |
| 90-180s | gradient < 4% | -1.5 |
| >= 180s | any | 0.0 (sustained effort) |

**Duration cutoff:** 90s (recalibrated from 60s, 2026-03-21)

### H10 — Topographic Isolation (`_h10_isolation_bonus`)
**Range:** [-1.5, +2.0]

Measures pre/post climb flatness and onset steepness. Implemented 2026-03-22.

| Signal | Window | Condition | Bonus |
|--------|--------|-----------|-------|
| Pre-climb flat | 60s before | rise < 3m | +0.75 |
| Pre-climb climbing | 60s before | rise > 5m | -0.75 |
| Post-climb flat | 60s after | rise < 3m | +0.75 |
| Post-climb climbing | 60s after | rise > 5m | -0.75 |
| Steep onset | 15s onset vs pre | onset_grad > 0.5, pre_grad < 0.1 | +0.5 |
| Large vert discount | — | vert >= 50m + negative bonus | penalty * 0.3 |

### H12 — Frequency Prior (`_h12_frequency_prior_bonus`)
**Range:** [0, +1.0] (capped — see audit note below)

Historical detection frequency at GPS location (H3 res 8, ~460m hexagons).

| Detection Count | Bonus |
|----------------|-------|
| 20+ | +1.0 |
| 10-19 | +0.75 |
| 5-9 | +0.5 |
| 2-4 | +0.25 |
| 0-1 | 0.0 |

**Cap rationale:** Capped at +1.0 (audit RED H12-decay). A false positive at a
location permanently inflates frequency count. Until the map uses cross-family
corroboration and/or temporal decay, the cap prevents positive feedback loops.

**Application guard:** H12 is only applied to candidates with cross-family
corroboration, e.g. momentum plus persistence. It is ignored for single-source
and same-family-only candidates so the frequency map cannot mint acceptance on
its own.

**Eval note:** H12 uses a frequency map that is currently built from the full
corpus. For honest holdout evaluation, the map must be rebuilt from train-only
data or disabled entirely. See `tools/corpus/run_holdout_eval.py`.

---

## Scoring Formula

```
total = strength + source_prior + support_bonus + weak_support_bonus
      + h3_bonus + h4_bonus + h9_bonus + h2_bonus + h10_bonus + h12_bonus
      - fragmentation_penalty - quality_penalty

threshold = CANONICAL_V2_MIN_SCORE (2.25)
  + SINGLE_SOURCE_PENALTY (0.75) if no cross-family corroboration and family != persistence
  + 0.5 if sparse sampling
  + 0.25 if degraded elevation and vert < 35m
  + 2.0 if sparse sampling, vert < 60m, and average gradient < 2%
  + 99.0 if momentum:urban_hills, vert < 35m, and no steep-isolated exception

total += MOMENTUM_CONSENSUS_EPSILON_BONUS (0.08) if the consensus predicate passes

accept if total >= threshold
```

`h12_bonus` is included only when `corroborating_families` is non-empty.

**Weak support and suppression (implemented scorer):**

- `weak_support_bonus` is 0.60 only when raw-persistence weak-support count is
  positive, the candidate family is not `persistence`, and H3 bonus is at least
  -1.0; otherwise it is zero (`climb.py:1835–1842,2423–2429`). This does not
  remove the single-source threshold penalty or enable H12.
- Sparse, low-gradient suppression adds 2.0 to the threshold when all three
  conditions above hold; a missing average gradient is treated as 0.0 for this
  check (`climb.py:2452–2458`).
- Urban momentum candidates below 35m receive the 99.0 threshold addition
  unless they have `20m <= vert < 35m`, at least 7% average gradient, 90s
  duration, 250m distance, H4 bonus >= 1.0 and H10 bonus >= 0.75
  (`_is_steep_isolated_urban_micro_candidate`, `climb.py:2310–2330,2459–2471`).
- The final 0.08 consensus addition is conditional on
  `_should_apply_momentum_consensus_epsilon`, including a positive score gap
  no larger than 0.08 and its evidence/quality gates (`climb.py:2331–2364,2473–2485`).

**Corroboration discounts:**
- Cross-family corroboration: +1.5 per family
- Same-family corroboration: +0.5
- Corroborated high-vert (>= 100m): fragmentation penalty * 0.3

---

## Evaluation Metrics (as of 2026-05-02)

| Mode | Precision | Recall | F1 | Notes |
|------|-----------|--------|----|-------|
| Scientific holdout | 0.821 | 0.749 | 0.783 | H12 off; no bridge preprocessing; 131 eval rides |
| Deployment holdout | 0.825 | 0.739 | 0.780 | H12 cross-family guard + bridge preprocessing |

**Guard impact:** Deployment before the H12 cross-family guard was
P=0.821/R=0.737/F1=0.777 with 642 matches, 229 misses, and 140 extras. After
the guard: 644 matches, 227 misses, and 137 extras.

**Known eval gaps:**
1. Deployment mode still uses a full-corpus frequency map; rebuild H12 from
   train-only data for a fully honest prior.
2. Geography eval should use symmetric H12/bridge settings across regions.
3. Scientific mode intentionally disables bridge preprocessing; use deployment
   mode for production policy checks.

---

## Parameter Sweep Mapping

For sweep scripts in `tools/corpus/`, these abbreviations map to production code:

| Sweep Param | Production Equivalent | Current Value |
|-------------|----------------------|---------------|
| SSP | CANONICAL_V2_MIN_SCORE | 2.25 |
| RSS | (redundant score suppress threshold) | 0.50 |
| RTG | (ride terrain gain weight) | 1 |
| PST | (persistence min time) | 25 |
| H3V | notable_vert standout multiplier | 2.0 |
| H9D | roller filter duration cutoff | **90s** |
| H4I | intensity top tier threshold | **50,000** |
