# Climb Detection v2: Persistent Homology Architecture

*February 2026 — Design specification for workout-parse climb detection rewrite*

**Status:** HISTORICAL — earlier detector design approval

**Replaces:** Momentum-based detector (`workout-parse/src/climb/detector.rs`), SHA256 signatures (`signature.rs`), discrete terrain classification (`terrain.rs`)

**Review history:**
- Round 1: Professor identified 3 critical issues (pairing convention, GPD threshold, cosine similarity)
- Round 2: All 3 fixed + 5 robustness additions (uncertainty, diagnostics, caps, calibration, bias)
- Final review: **GO** — scores 9/10, 7/10, 7.5/10, 9/10 across components

Current canon-first identity and the detector freeze are governed by [PROTOCOL_TRUTHS.md](PROTOCOL_TRUTHS.md) and [FRESHEST_SPEC.md](FRESHEST_SPEC.md), with existing detector parameters in [DETECTOR_PARAMS.md](DETECTOR_PARAMS.md).

---

## Table of Contents

1. [Design Philosophy](#1-design-philosophy)
2. [Pipeline Overview](#2-pipeline-overview)
3. [Component 1: 0D Persistent Homology](#3-component-1-0d-persistent-homology)
4. [Component 2: Noise Floor (Gumbel EVT)](#4-component-2-noise-floor-gumbel-evt)
5. [Component 3: Geographic Significance (GPD)](#5-component-3-geographic-significance-gpd)
6. [Component 4: DCT Signatures v2](#6-component-4-dct-signatures-v2)
7. [Migration from v1](#7-migration-from-v1)
8. [Implementation Plan](#8-implementation-plan)
9. [Open Items](#9-open-items)
10. [References](#10-references)

---

## 1. Design Philosophy

The v1 climb detector uses a momentum-based heuristic with **90 hand-tuned parameters** across 5 terrain presets. It works, but:

- Parameters were calibrated by feel, not derived from physics
- Terrain classification is a discrete 4-category system that breaks at boundaries
- SHA256 signatures destroy similarity (avalanche function)
- No principled noise handling — thresholds are educated guesses
- Trim heuristics guess where climbs start/end instead of computing boundaries

**v2 replaces heuristics with mathematics:**

| Aspect | v1 (Current) | v2 (This Spec) |
|--------|-------------|----------------|
| Detection | Momentum accumulator (90 params) | 0D persistent homology (0 params) |
| Boundaries | Trim heuristic (gradient scan) | Topological birth/death (exact) |
| Noise floor | 15-100m vert_min (guessed) | 3.0m (Gumbel EVT derived) |
| Terrain context | 4 discrete classes | Continuous GPD ξ per H3 cell |
| Significance | None (all climbs equal) | GPD survival probability |
| Signatures | SHA256 gradient hash (broken similarity) | DCT-II coefficients (similarity-preserving) |
| Matching | Hamming distance on SHA256 bits (meaningless) | Relative Euclidean on DCT coefficients |
| Parameters | 90 hand-tuned | 1 derived constant + 3 fitted per cell |

**The "aha":** One algorithm extracts ALL elevation features at ALL scales simultaneously. No tuning. No terrain presets. Significance comes from geography, not from the ride. The persistence diagram IS the complete description of the terrain's topological features.

---

## 2. Pipeline Overview

```
Ride GPS
  → SMA Smooth (window=5 samples)
  → 0D Persistence (union-find + merge tree, O(n))
      → All features at all scales, with exact boundaries
      → Hierarchical nesting via merge tree
  → Noise Gate (τ = 3.0m, Gumbel EVT derived)
      → Discard features below barometric noise floor
  → GPD Significance Scoring
      → Per H3-res5 cell: adaptive threshold, PWM estimation
      → Conservative scores with uncertainty bounds
      → Sample-size-derived caps (never overstate confidence)
  → DCT-II Signature v2 (64 bytes)
      → 16 f16 coefficients, BLAKE3 checksum
      → H3 anchor for geographic disambiguation
  → Multi-Gate Vault Matching
      → Version → H3 proximity → Geometric → DCT distance
```

**Parameter count:** τ = 3.0m is derived from sensor physics. Per geographic cell: threshold u, GPD (ξ, σ) are fitted from DEM data. Application-level filters (min_distance=500m, min_gradient=2%) are user-facing preferences, not algorithmic parameters.

---

## 3. Component 1: 0D Persistent Homology

### 3.1 Mathematical Foundation

Given a piecewise-linear elevation function f: [0, L] → R, the **sublevel set** at threshold t is:

```
F_t = { x ∈ [0, L] : f(x) ≤ t }
```

As t increases from -∞ to +∞, connected components of F_t appear and merge:

- **Birth** at value b: A new component appears at a **local minimum** (valley) with elevation b.
- **Death** at value d: Two components merge at a **local maximum** (peak) with elevation d. The younger component (higher birth value) dies per the **Elder Rule**.

**Key correctness property:** In 1D sublevel-set persistence, death occurs at local maxima. The climb corresponding to a persistence pair (b, d) runs from the **valley** (birth, local minimum) **up to the peak** (death, local maximum). Death IS the peak, NOT another valley.

**Persistence** = d - b = the minimum elevation change needed to eliminate this feature. It is a measure of topological significance.

### 3.2 The Elder Rule

When two components merge at a local maximum:
- The component born at the **lower** elevation survives (the "elder")
- The component born at the **higher** elevation dies (the "younger")
- Ties broken by index: lower index survives

This produces persistence pairs (b, d) where b < d (in elevation).

### 3.3 Algorithm

O(n·α(n)) ≈ O(n) via union-find. Process all samples in elevation-sorted order.

```rust
// Pseudocode — actual Rust implementation follows
fn compute_persistence(elev: &[f64]) -> (Vec<PersistencePair>, MergeTree) {
    let order = argsort_by(elev, |a, b| (elev[a], a).cmp(&(elev[b], b)));
    let mut uf = UnionFind::new(elev.len());
    let mut alive = vec![false; elev.len()];
    let mut birth_of = HashMap::new();  // component root → birth index
    let mut pairs = Vec::new();
    let mut tree = MergeTree::new();

    for &i in &order {
        alive[i] = true;
        let left = (i > 0 && alive[i - 1]).then(|| uf.find(i - 1));
        let right = (i < elev.len() - 1 && alive[i + 1]).then(|| uf.find(i + 1));

        match (left, right) {
            (None, None) => {
                // Birth: new component at local minimum
                birth_of.insert(i, i);
                tree.add_leaf(i, elev[i]);
            }
            (Some(r), None) | (None, Some(r)) => {
                // Extend existing component
                uf.union(r, i);
                let root = uf.find(i);
                birth_of.insert(root, birth_of[&r]);
            }
            (Some(lr), Some(rr)) if lr == rr => {
                // Same component, just absorb
                uf.union(lr, i);
                let root = uf.find(i);
                birth_of.insert(root, birth_of[&lr]);
            }
            (Some(lr), Some(rr)) => {
                // MERGE: two different components meet at local maximum i
                let lb = birth_of[&lr];
                let rb = birth_of[&rr];

                let (elder, younger) = if (elev[lb], lb) < (elev[rb], rb) {
                    (lr, rr)
                } else {
                    (rr, lr)
                };
                let younger_birth = birth_of[&younger];
                let elder_birth = birth_of[&elder];

                pairs.push(PersistencePair {
                    birth_idx: younger_birth,
                    birth_elev: elev[younger_birth],
                    death_idx: i,
                    death_elev: elev[i],
                    persistence: elev[i] - elev[younger_birth],
                    is_essential: false,
                });

                tree.add_internal(i, elev[i], elder_birth, younger_birth);

                uf.union(elder, i);
                uf.union(uf.find(i), younger);
                let root = uf.find(i);
                birth_of.insert(root, elder_birth);
            }
        }
    }

    // Essential class: global minimum, never dies
    let global_min = order[0];
    let global_max = *elev.iter().enumerate()
        .max_by(|a, b| a.1.partial_cmp(b.1).unwrap()).unwrap().0;
    // ... emit synthetic essential pair ...

    (pairs, tree)
}
```

### 3.4 Merge Tree

The merge tree captures hierarchical nesting of climbs:

- **Leaf nodes** = local minima (valleys)
- **Internal nodes** = local maxima (merge points / peaks)
- **Parent-child** = the child's component was absorbed at the parent's elevation

Example — Galibier via Télégraphe:
```
              2642m (Galibier summit)       ← root
             /                    \
     1566m (Col du Télégraphe)    600m (Valloire)   ← leaves
        /            \
   1460m (dip)      ...
```

At persistence threshold ε:
- ε = 50m: Both the sub-climb (106m persistence) and full climb (2042m) are significant → nested structure reported
- ε = 200m: Only the full climb → intermediate dip smoothed out

### 3.5 Data Structures

```rust
/// A persistence pair from sublevel-set filtration.
///
/// The climb runs from birth_idx (valley) UP TO death_idx (peak).
/// death_idx is the PEAK where this component merges with an older one.
pub struct PersistencePair {
    pub birth_idx: usize,        // local minimum (valley)
    pub birth_elev: f64,
    pub death_idx: usize,        // local maximum (peak)
    pub death_elev: f64,
    pub persistence: f64,        // death_elev - birth_elev
    pub is_essential: bool,      // global min → global max synthetic pair
}

/// Merge tree node.
pub struct MergeTreeNode {
    pub sample_idx: usize,
    pub elevation: f64,
    pub is_leaf: bool,           // true = local minimum
    pub children: Vec<usize>,    // indices into MergeTree.nodes
    pub parent: Option<usize>,
}

/// A detected climb with hierarchical structure.
pub struct Climb {
    pub start_idx: usize,        // valley
    pub summit_idx: usize,       // peak
    pub start_elev: f64,
    pub summit_elev: f64,
    pub start_distance_m: f64,
    pub summit_distance_m: f64,
    pub elevation_gain: f64,
    pub persistence: f64,
    pub is_boundary: bool,       // start or summit at ride edge
    pub is_essential: bool,
    pub sub_climbs: Vec<Climb>,  // nested features
    pub geo_significance: Option<f64>,  // GPD score, filled later
}
```

### 3.6 Edge Cases

**Ride starts mid-climb:** Endpoint treated as local extremum based on neighbor. The is_boundary flag marks the resulting climb as potentially truncated.

**Ride ends mid-climb:** Essential class captures the climb from deepest valley to the highest point. Flagged with is_boundary=true.

**Plateaus:** Simulation of simplicity via sort key (elevation, index) breaks all ties deterministically. No special-case code needed.

**Out-and-back rides:** Run persistence on both forward and reversed profiles. Deduplicate: two features are the same climb if their H3 anchor cells (midpoints) are within grid distance 2 AND their persistence values differ by less than 20%.

**Directional filtering:** For forward-direction climbs, keep pairs where birth_idx < death_idx. The merge tree structure is preserved under this filter (guaranteed by Elder Rule index ordering).

### 3.7 Parameters

The persistence computation itself uses **zero parameters**. Post-filtering:

| Filter | Value | Source |
|--------|-------|--------|
| min_persistence | 3.0m | Gumbel EVT noise floor (Component 2) |
| min_distance | 500m | Application preference |
| min_avg_gradient | 2% | Application preference |

---

## 4. Component 2: Noise Floor (Gumbel EVT)

### 4.1 Problem

GPS/barometric elevation noise creates spurious persistence features. We need a principled noise floor τ below which features are indistinguishable from sensor noise.

### 4.2 Derivation

**Sensor model:** BMP280 barometric altimeter (standard in Wahoo/Garmin cycling computers), σ = 1.0m per sample.

**After SMA smoothing** (window w = 5 samples):
```
σ_smoothed = σ / √w = 1.0 / √5 = 0.447m
```

**Maximum spurious persistence** in a noise-only signal of N samples:

The number of independent persistence features is approximately k_eff = N/(2w). For a 6-hour ride at 1Hz: N = 21,600, so k_eff = 2,160.

The maximum of k_eff features follows a Gumbel distribution:
```
μ = σ_s × √(2·ln(k_eff))
β = σ_s / √(2·ln(k_eff))
```

At 99.9% confidence:
```
P_max = μ + β × (-ln(-ln(0.999)))
      = 0.447 × 3.919 + 0.114 × 6.907
      = 1.752 + 0.787
      = 2.54m
```

### 4.3 Chosen Value

**τ = 3.0m** (includes ~20% safety margin over the Gumbel 99.9% quantile of 2.54m).

The safety margin accounts for:
- Non-independence between adjacent persistence features (the Gumbel derivation assumes independence)
- Device-to-device variation in barometric sensor noise
- Atmospheric pressure fluctuations during long rides

**GPS-only elevation** (no barometer): σ ≈ 15-25m → τ ≈ 45m. GPS-only devices are unsuitable for fine-grained climb detection.

### 4.4 Usage

Any persistence pair with persistence < τ is classified as noise and discarded before significance scoring.

---

## 5. Component 3: Geographic Significance (GPD)

### 5.1 Goal

Score each climb relative to its geographic neighborhood. A 30m hill in the Netherlands should score higher than a 30m hill in the Alps, because 30m is remarkable in flat terrain but ordinary in mountains.

### 5.2 Spatial Framework

**Unit:** H3 resolution-5 cells (~253 km², ~8.7km edge-to-edge).

**Data source:** FABDEM (Forest And Buildings removed Copernicus DEM), 30m resolution, free, global coverage. Strips vegetation artifacts that plague raw SRTM.

**Bootstrap process** (runs once per cell):
1. Extract road network polylines from OSM within the cell
2. Sample elevation profiles along roads from FABDEM (bilinear interpolation)
3. Run 0D persistence on each road segment
4. Collect all persistence values → fit GPD

**Cost:** ~8MB compressed for global coverage. $5-10 total compute. ~11 hours single machine.

### 5.3 Threshold Selection

Search quantiles 0.80–0.95 for the **parameter stability region** where ξ̂ is approximately constant:

```
CANDIDATES = [0.80, 0.85, 0.90, 0.95]

for q in CANDIDATES:
    u_q = quantile(persistence_values, q)
    k_q = count(values > u_q)
    if k_q < 12: skip  // minimum for reliable GPD estimation
    (ξ̂_q, σ̂_q) = fit_gpd_pwm(exceedances above u_q)

Find lowest q where ξ̂ range < 0.15 across all higher thresholds.
Default to 85th percentile if no clear stability.
```

**Floor:** Never below 80th percentile (pre-asymptotic bias too high below this).

**Minimum exceedance counts:**

| k | Assessment | Action |
|---|-----------|--------|
| < 8 | Insufficient | Empirical mode (no GPD) |
| 8–11 | Marginal | Empirical mode (conservative) |
| 12–29 | Adequate | PWM estimation |
| ≥ 30 | Good | PWM estimation (MLE optional) |

### 5.4 GPD Estimation: PWM Only

Per the professor's recommendation, we use **PWM (L-moments) everywhere**. No MLE. This eliminates Newton-Raphson convergence issues and simplifies the confidence interval computation.

Given sorted exceedances y₁ ≤ y₂ ≤ ... ≤ y_k above threshold u:

```
b₀ = (1/k) Σ yᵢ                          // mean exceedance
b₁ = (1/k) Σ ((i-1)/(k-1)) × yᵢ         // weighted mean

ξ̂ = 2 - b₀/(b₀ - 2b₁)
σ̂ = 2b₀b₁/(b₀ - 2b₁)
```

Valid for ξ < 0.5 (covers all realistic terrain). Clamp ξ̂ to [-0.49, 0.49].

**Confidence interval** (analytic asymptotic variance):
```
Var(ξ̂) ≈ (1 + ξ̂)² × (1 + 2ξ̂)² / (k × (3 + 2ξ̂)² × (4 + 2ξ̂))
ξ_hi = ξ̂ + 1.645 × √Var(ξ̂)    // 90% upper bound
```

### 5.5 Terrain Interpretation via ξ

The shape parameter **automatically encodes terrain type** — no classification step needed:

| ξ Range | Terrain | Interpretation | Example |
|---------|---------|---------------|---------|
| ξ > 0.1 | Mountainous | Heavy tail — there's always a bigger climb | Alps, Rockies |
| -0.05 < ξ < 0.1 | Rolling | Exponential — features decay predictably | UK, Eastern US |
| ξ < -0.05 | Flat | Bounded — finite maximum possible feature | Netherlands, Kansas |

For ξ < 0: the GPD has a finite upper endpoint at u + σ/|ξ|. This is physically correct — in flat terrain, there IS a maximum possible climb.

### 5.6 Score Computation

**Scoring function:**
```
G(p) = -log₁₀(survival_probability) / log₁₀(1000)
```

Bounded to [0, 1]. A score of 0.33 means 1-in-10 rarity, 0.67 means 1-in-100, 1.0 means 1-in-1000.

**For p > threshold u (GPD regime):**
```
y = p - u                                    // exceedance
S_gpd = (1 + ξ̂·y/σ̂)^(-1/ξ̂)                // GPD survival (ξ ≠ 0)
S_gpd = exp(-y/σ̂)                            // GPD survival (ξ = 0)
survival = (k/n) × S_gpd                     // overall survival
G_point = -log₁₀(survival) / 3               // point estimate
```

**Conservative score (ALWAYS used for decisions):**
```
S_conservative = (k/n) × (1 + ξ_hi·y/σ̂_hi)^(-1/ξ_hi)
G_conservative = -log₁₀(S_conservative) / 3
G_uncertainty = G_point - G_conservative
```

Higher ξ = heavier tail = less surprising = lower score. Using ξ_hi (upper CI bound) produces the defensible lower bound on significance.

**For p ≤ threshold u (below-threshold):**
```
survival = (k/n) + (1 - k/n) × (1 - p/u)    // linear interpolation
G = -log₁₀(survival) / 3
```

### 5.7 Sample-Size Score Caps

Derived from Beta(1, k) posterior at 90% confidence. The maximum defensible score with k exceedances:

```
G_cap(k) = -log₁₀((1 - q) × (1 - 0.10^(1/k))) / 3
```

where q = threshold quantile (~0.85).

| k | G_cap | Meaning |
|---|-------|---------|
| 4 | 0.39 | Cannot claim > 0.39 with 4 exceedances |
| 7 | 0.46 | |
| 10 | 0.50 | |
| 15 | 0.55 | |
| 20 | 0.59 | |
| 30 | 0.64 | |
| 50+ | uncapped | Full GPD confidence |

**Previous cap was 0.70 for all empirical estimates — this was ~3x too generous at typical small k.**

### 5.8 Bias Correction

Compute threshold stability slope B_ξ (linear regression of ξ̂ across candidate thresholds):

```
If |B_ξ × (u_selected - u_min)| > 0.5 × SE(ξ̂):
    ξ̂_corrected = ξ̂ - (B_ξ × σ̂) / k
    Add |ξ̂ - ξ̂_corrected| to G_uncertainty
```

This is a secondary defense. The primary protection against pre-asymptotic bias is the raised 80th-percentile threshold floor.

### 5.9 Tail Diagnostics

Three diagnostics, cell passes if ≥ 2 of 3 pass:

**1. Hill Stability (tests tail index directly):**
```
For m = 5, ..., floor(k/3):
    H_m = (1/m) × Σ ln(x_(n-i+1) / x_(n-m))   for i = 1..m
Pass if max|H_m - ξ̂| < 0.3 for all m in range
```

**2. Tail Ratio (tests tail density):**
```
q90 = GPD quantile at 10% survival of exceedances
T_r = count(exceedances > q90) / (k × 0.10)
Pass if T_r ∈ [0.3, 2.5] for k ≥ 20
Pass if T_r ∈ [0.1, 4.0] for k < 20
```

**3. Mean Excess Linearity (tests GPD assumption):**
```
ME(u) = mean of (x - u) for x > u
Compute for u ∈ [threshold, q75 of exceedances]
Pass if R² > 0.80 of linear fit
```

**If diagnostics fail:** Cap scores at 0.60, add 0.10 to G_uncertainty.

### 5.10 Cross-Cell Calibration

Post-processing after all cells scored:

```
For each cell c with n_c ≥ 20:
    CR(c, q) = count(G > q in c) / (n_c × 10^(-3q))
    for q ∈ {0.3, 0.4, 0.5, 0.6}

If median(CR) deviates from 1.0 by > 0.3 at any q:
    Apply PIT recalibration: G*(p) = EmpiricalCDF_global(G(p))
    NOTE: After PIT, scores become rank-based (not probability-based)

For cross-cell comparisons:
    |G_A - G_B| > 1.65 × √(Var(G_A) + Var(G_B))
    required to declare meaningful difference
```

### 5.11 Output Per Feature

```rust
pub struct SignificanceScore {
    pub g_score: f32,            // conservative (use for decisions)
    pub g_point: f32,            // point estimate (reference)
    pub g_uncertainty: f32,      // score uncertainty width
    pub confidence_tier: ConfidenceTier,  // empirical | low | moderate | full
    pub tail_diag_pass: bool,
    pub bias_corrected: bool,
}

pub enum ConfidenceTier {
    Empirical,   // k < 12, empirical quantiles + cap
    Low,         // 12 ≤ k < 20, PWM + cap
    Moderate,    // 20 ≤ k < 30, PWM, uncapped if diagnostics pass
    Full,        // k ≥ 30, PWM + full uncertainty propagation
}
```

### 5.12 Cell Data Structure

```rust
pub struct TerrainCell {
    pub h3_index: u64,           // H3 res-5 cell
    pub n_features: u16,
    pub k_exceedances: u16,
    pub threshold: f32,          // selected threshold u (meters)
    pub threshold_quantile: f32, // which quantile (0.80-0.95)
    pub gpd_xi: f32,             // shape parameter
    pub gpd_sigma: f32,          // scale parameter
    pub xi_ci_hi: f32,           // 90% upper bound on xi
    pub g_cap: f32,              // sample-size-derived score cap
    pub confidence_tier: u8,
    pub tail_diag_pass: bool,
    pub bias_corrected: bool,
    pub bias_slope: f32,         // B_xi for metadata
    pub calibration_ratio_05: f32, // CR at q=0.5
}
```

---

## 6. Component 4: DCT Signatures v2

### 6.1 Problem Solved

The v1 signature hashes the 32-bin gradient profile with SHA256. SHA256 is an avalanche function — one changed input bit flips ~50% of output bits. This makes the "similarity" computation (Hamming distance on SHA256 output) mathematically meaningless. Two nearly identical gradient profiles are indistinguishable from random noise.

DCT coefficients preserve geometric similarity by construction (Parseval's theorem).

### 6.2 Gradient Profile Construction

Same as v1:
1. Divide climb distance into 32 equal bins
2. Compute average gradient per bin
3. Normalize to [-10%, +20%] range → [0, 255] byte values

### 6.3 DCT-II Transform

Compute orthonormal DCT-II of the 32-bin profile, keep first 16 coefficients:

```
c[k] = √(2/N) × Σ x[n] × cos(π(2n+1)k / 2N)    for k = 0..15
```

with the standard √(1/N) normalization for k=0.

**Energy retained:** 99.96% (verified across 10,000 synthetic profiles).

**What each coefficient captures:**

| Coefficient | Physical Meaning | Energy Share |
|------------|-----------------|-------------|
| c[0] | Average gradient (DC component) | ~79% |
| c[1] | Overall tilt — gets steeper or shallower? | ~2-5% |
| c[2-3] | Major shape features (one or two big bumps) | ~1-5% each |
| c[4-8] | Medium structure | ~0.5-7% each |
| c[9-15] | Fine structure | ~0.1-0.5% each |
| c[16-31] | Noise floor (discarded) | <0.1% total |

**c[0] carries ~79% of energy and MUST participate in matching.** This is precisely why cosine similarity fails — it normalizes away the DC component, making a 5% hill indistinguishable from a 15% hill.

### 6.4 Similarity Metric: Relative Euclidean Distance

```
d_rel(x, y) = ||c_x - c_y||₂ / (0.5 × (||c_x||₂ + ||c_y||₂))
```

**Properties:**
- Scale-sensitive: d_rel(A, 2A) = 2/3 (clear non-match)
- Noise-tolerant: GPS noise (σ=0.15%/bin) produces d_rel ≈ 0.014
- Bounded: d_rel ∈ [0, 2]
- O(1): 16 multiplications + 16 additions + 2 square roots + 1 division
- NOT a true metric (fails triangle inequality), but fine for pairwise comparison

**Why NOT cosine similarity:**
```
Profile A = [5, 6, 8, 7, 5, 4, 6, 8]     (gentle roller, mean ~6%)
Profile B = [10, 12, 16, 14, 10, 8, 12, 16] (same shape, 2x steeper)
cosine_similarity(DCT(A), DCT(B)) = 1.0    ← WRONG, these are different climbs
d_rel(DCT(A), DCT(B)) = 0.667              ← correct, clear non-match
```

### 6.5 Matching Thresholds (Monte Carlo Validated)

| d_rel Range | Classification | Source |
|-------------|---------------|--------|
| < 0.08 | **Match** | Same climb + GPS noise: mean=0.014, max=0.040 |
| 0.08 – 0.12 | **ProbableMatch** | Boundary shift cases |
| ≥ 0.12 | **NoMatch** | Different climbs: min=0.092 after geometric gate |

**Gap factor:** 2.3x between worst-case same-climb (0.040) and best-case different-climb (0.092).

### 6.6 Multi-Gate Matching Pipeline

```rust
fn match_signatures(a: &SignatureV2, b: &SignatureV2) -> MatchResult {
    // Gate 0: Version compatibility
    if a.version != b.version { return Incompatible; }

    // Gate 1: Geographic proximity
    if h3_grid_distance(a.h3_anchor, b.h3_anchor) > 3 { return NoMatch; }

    // Gate 2: Geometric pre-filter
    if rel_diff(a.vert_m, b.vert_m) > 0.15 { return NoMatch; }
    if rel_diff(a.distance_m, b.distance_m) > 0.15 { return NoMatch; }

    // Gate 3: DCT shape match
    let d = rel_euclidean(&a.dct_coeffs, &b.dct_coeffs);
    match d {
        d if d < 0.08 => Match { confidence: 1.0 - d / 0.08 },
        d if d < 0.12 => ProbableMatch { confidence: 1.0 - (d - 0.08) / 0.04 },
        _ => NoMatch,
    }
}
```

### 6.7 f16 Precision

IEEE 754 half-precision: 1 sign + 5 exponent + 10 mantissa bits.

- Range: ±65,504 (sufficient for DCT coefficients)
- Relative precision: ~0.1% (3.3 decimal digits)
- Quantization noise contribution to d_rel: **0.000329** (2.4% of GPS noise)
- Verdict: **f16 is fine.** Compute in f32, store in f16, promote to f32 for comparison.

Use the `half` crate in Rust.

### 6.8 64-Byte Signature v2 Layout

```
Offset  Size  Type     Field                Description
------  ----  ------   -----                -----------
0       1     u8       version              0x02 for DCT format
1       1     u8       flags                terrain(2b), direction(1b), power(1b), reserved(4b)
2       2     u16 BE   vert_m               vertical gain in meters (0-65535)
4       2     u16 BE   distance_m           horizontal distance in meters (0-65535)
6       2     i16 BE   avg_gradient_x100    average gradient × 100 (e.g., 850 = 8.50%)
8       8     u64 BE   h3_anchor            H3 resolution 10 cell at climb midpoint
16      32    f16[16]  dct_coeffs           orthonormal DCT-II coefficients
48      16    [u8;16]  checksum             BLAKE3(bytes[0..48]) truncated to 128 bits
```

**Flags byte:**
```
Bit 7-4: Reserved (0000)
Bit 3-2: Terrain class (00=flat, 01=rolling, 10=hilly, 11=mountainous)
Bit 1:   Direction (0=N/E dominant, 1=S/W dominant)
Bit 0:   Has power data (0=no, 1=yes)
```

**Changes from v1:**
- SHA256 gradient hash → 16 DCT coefficients (bytes 16-47)
- MD5 checksum → BLAKE3 (bytes 48-63)
- f32 metrics → u16/i16 (bytes 2-7, more compact)
- Added H3 anchor (bytes 8-15, geographic disambiguation)
- **Duration removed** — it encodes rider speed, not climb identity

---

## 7. Migration from v1

1. New signatures generated with version `0x02`
2. Old signatures (implicit version `0x01`) remain valid but cannot match against v2
3. Rides with v1 signatures get re-processed to generate v2 signatures alongside
4. `indexed_vaults.signature_hex` gains a `signature_version` column
5. Once all vaults have v2 signatures, v1 can be deprecated

**Database migration:**
```sql
ALTER TABLE indexed_vaults ADD COLUMN signature_version SMALLINT DEFAULT 1;
ALTER TABLE indexed_vaults ADD COLUMN signature_v2_hex CHAR(128);
-- Backfill v2 signatures by re-processing stored ride data
```

---

## 8. Implementation Plan

### Phase 1: Persistence + Merge Tree (Rust, ~120 lines)

**Files:** New `workout-parse/src/climb/persistence.rs`

1. `compute_persistence()` — union-find sweep, returns pairs + merge tree
2. `extract_climbs()` — directional filtering, nesting from merge tree
3. Property-based tests via proptest:
   - All birth_elev < death_elev
   - Sum of finite persistences + essential = total elevation range
   - Merge tree is a valid binary tree
   - Directional filter preserves merge tree structure

### Phase 2: DCT Signature v2 (Rust, ~150 lines)

**Files:** Replace `workout-parse/src/climb/signature.rs`

1. `generate_signature_v2()` — gradient profile → DCT → f16 → pack 64 bytes
2. `match_signatures()` — multi-gate matching pipeline
3. `rel_euclidean_f16()` — promote to f32, compute distance
4. Tests: round-trip encoding, known-profile DCT values, matching thresholds

### Phase 3: GPD Bootstrap Tooling (Python, runs once)

**Files:** New `backend/app/services/terrain_bootstrap.py`

1. FABDEM elevation sampling along OSM roads
2. Persistence computation per road segment (call Rust via PyO3)
3. PWM fitting per H3-res5 cell
4. Threshold selection + diagnostics
5. Output: terrain cell database (SQLite or Supabase table)

### Phase 4: Wire Into Dev Dashboard

1. Visualize persistence diagram for any ride
2. Show merge tree with nesting
3. Overlay GPD significance scores on detected climbs
4. Compare v1 (momentum) vs v2 (persistence) side by side

### Phase 5: Production Integration

1. Replace momentum detector call in `ride_processor.py`
2. Generate v2 signatures alongside v1 during transition
3. Update vault matching to use multi-gate pipeline
4. Backfill existing rides

---

## 9. Open Items

Items identified during review that need resolution during implementation:

1. **FABDEM preprocessing pipeline details:** How to handle road intersections (per-segment vs full-graph persistence), tunnels, bridges, interpolation method for 30m DEM.

2. **Merge tree serialization format:** For persisting/transmitting tree structure. Likely a flat array of nodes with parent pointers.

3. **Epoch boundary for geographic scoring:** Cell statistics are computed once (offline bootstrap) and updated incrementally as more rides provide ground-truth calibration data. Clarify update schedule.

4. **Smoothing upgrade:** Professor suggests Gaussian kernel (σ=50m horizontal distance) instead of SMA. Evaluate in Phase 1 — SMA is simpler and may be sufficient.

5. **v1 compatibility period:** How long to maintain dual v1/v2 signatures. Depends on vault count and re-processing timeline.

---

## 10. References

### Persistent Homology
- Edelsbrunner, H., Letscher, D., & Zomorodian, A. (2002). Topological persistence and simplification. *Discrete & Computational Geometry*, 28(4), 511-533.
- Cohen-Steiner, D., Edelsbrunner, H., & Harer, J. (2007). Stability of persistence diagrams. *Discrete & Computational Geometry*, 37(1), 103-120.

### Extreme Value Theory
- Pickands, J. (1975). Statistical inference using extreme order statistics. *Annals of Statistics*, 3(1), 119-131.
- Balkema, A. A. & de Haan, L. (1974). Residual life time at great age. *Annals of Probability*, 2(5), 792-804.
- Hosking, J. R. M. & Wallis, J. R. (1987). Parameter and quantile estimation for the Generalized Pareto Distribution. *Technometrics*, 29(3), 339-349.
- Coles, S. (2001). *An Introduction to Statistical Modeling of Extreme Values.* Springer.

### Signal Processing
- Ahmed, N., Natarajan, T., & Rao, K. R. (1974). Discrete cosine transform. *IEEE Transactions on Computers*, 23(1), 90-93.

### DEM Data
- Hawker, L., et al. (2022). A 30m global map of elevation with forests and buildings removed. *Environmental Research Letters*, 17(2).

### Geospatial
- Uber H3: Hexagonal hierarchical geospatial indexing system. Resolution 10 ≈ 66m hexagons, Resolution 5 ≈ 253 km² hexagons.
