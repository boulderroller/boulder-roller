# Open Problems: Climb Detection v2

*February 2026 — Known gaps in our persistence-based climb detection architecture, shared for expert input*

---

## Context

We're building a cycling platform where climbs are first-class economic objects ("vaults"). Riders earn tokens by completing climbs, stake tokens in climbs they believe will attract traffic, and compete on leaderboards. **Correct climb detection, fair significance scoring, and stable fingerprinting are load-bearing for the economics.**

We've designed a v2 climb detection system that replaces ~90 hand-tuned parameters with four mathematical components. The design has been reviewed by an academic mathematician and scored 7–9/10 across components. The full spec is in `docs/CLIMB_DETECTION_V2_SPEC.md`. Here's the summary:

| Component | What It Does | Method |
|-----------|-------------|--------|
| **Detection** | Find every climb at every scale, with exact boundaries | 0D persistent homology (sublevel-set filtration, union-find, O(n)) |
| **Noise gate** | Discard features indistinguishable from sensor noise | Gumbel EVT on BMP280 barometric noise → τ = 3.0m at 99.9% confidence |
| **Significance** | Score each climb relative to its geographic area | GPD (Generalized Pareto Distribution) per ~250 km² H3 cell, PWM estimation |
| **Fingerprinting** | Match "same climb, different ride" with stable signatures | DCT-II coefficients (16 f16), relative Euclidean distance, 2.3x separation gap |

**Zero tunable parameters in detection.** One derived constant (noise floor). Three fitted parameters per geographic cell (threshold, ξ, σ). Application-level filters (min distance, min gradient) are user preferences, not algorithmic parameters.

The system below this is what we've designed. The problems below are what we haven't solved yet.

---

## Problem 1: Barometric Elevation Drift

### The issue

Our noise floor (τ = 3.0m) is derived from the **random** error of a BMP280 barometric altimeter: σ = 1.0m per sample, reduced to 0.447m after SMA(5) smoothing. The Gumbel 99.9% quantile for maximum spurious persistence in a noise-only signal is 2.54m. We use 3.0m with a 20% safety margin.

This handles **random noise** correctly. It does NOT handle **systematic drift**.

Barometric altitude is derived from atmospheric pressure. During a 3-hour ride, atmospheric pressure changes due to weather — fronts moving through, diurnal heating, etc. This creates a slow, monotonic elevation bias that accumulates over the ride. Typical magnitude: 10–30m over 3 hours. Extreme cases (weather front passage): 50m+.

**Impact on persistence:** The sublevel-set filtration operates on the elevation function as-given. A 20m upward drift over 3 hours tilts the entire elevation profile. This doesn't create false features (the tilt is monotonic), but it **shifts feature prominence values**. A climb near the start of the ride has its prominence measured against a lower baseline than the same climb near the end. A 50m climb at hour 0 and the same 50m climb at hour 3 would show different persistence values (e.g., 50m vs 35m) because the drifted baseline absorbs some of the apparent gain.

**Impact on signatures:** The DCT gradient profile is relatively robust to monotonic drift (gradient = d(elev)/d(distance), so a constant drift adds a small constant to all bins). But if the drift rate is not constant (which it typically isn't — pressure changes are episodic), it distorts the gradient shape.

**Impact on vault matching:** Two recordings of the same climb — one from a stable-pressure day, one from an active-weather day — will produce different prominence values and slightly different gradient profiles. This erodes the matching gap.

### What Strava does

Strava corrects barometric elevation against a DEM (digital elevation model) basemap post-ride. They use the GPS horizontal position to look up the "expected" elevation at each point, then apply a correction that removes systematic bias while preserving the barometric sensor's superior short-term precision.

The standard approach (used by Strava, Garmin Connect, and others):
1. Use GPS lat/lon to sample the DEM at each point
2. Compute a **single offset** or **piecewise linear correction** between the barometric trace and the DEM trace
3. Apply the correction to shift the barometric trace to match the DEM's absolute reference frame
4. The corrected trace retains the barometric sensor's relative precision (~1m) while removing the DEM's absolute bias (~few meters for SRTM/FABDEM)

### The question

**Should we correct elevation before running persistence?** The tradeoffs:

- **Pro:** Removes systematic drift, makes prominence values comparable across rides and conditions. Makes the noise floor derivation more valid (it assumes IID random noise, which is more true after drift removal). Improves vault matching stability.
- **Con:** Introduces a DEM dependency at ride-processing time (not just at bootstrap). DEM errors (~5m for FABDEM at 30m resolution) become a new error source. Urban areas with bridges, tunnels, and overpasses cause DEM mismatches. Requires lat/lon at every sample point (we have this — it's in `TileSample`).
- **Alternative:** Don't correct globally. Instead, compute persistence on the raw barometric trace, then when comparing two recordings of the "same" climb (vault matching), normalize prominence values relative to the local sub-segment. The DCT signature already operates on the gradient profile of just the climb segment, which is relatively short (2–30 minutes) and less affected by multi-hour drift.

We already plan to use FABDEM for the GPD terrain bootstrap. Do we also use it for ride-time elevation correction?

---

## Problem 2: Topological Boundaries vs Perceived Boundaries

### The issue

Persistent homology gives **mathematically exact** climb boundaries: birth at a local minimum (valley), death at a local maximum (peak). The climb runs valley → peak.

Cyclists don't think in valleys and peaks. They think in landmarks. "The climb starts at the roundabout after the bridge" or "it ends at the café on top." More precisely, they perceive a climb as starting where the **sustained effort** begins — where the gradient kicks up and stays up — not at the absolute lowest point, which might be a river crossing 200m before the real climbing starts.

**Concrete failure mode:** A valley has a small 2m dip at a stream crossing, then 200m of flat road, then the real climb begins. Persistence places the birth at the stream crossing (the absolute local minimum), not where the gradient steepens. The resulting climb boundary includes 200m of flat lead-in that the cyclist wouldn't consider part of the climb. The vault's distance, average gradient, and signature all include this flat section, diluting the climb's character.

The v1 system handled this with a `trim_climb_segment()` function that scans inward from both ends, removing samples where gradient < 4%. This is a heuristic, but it matches cyclist perception reasonably well.

### The question

**How do we reconcile topological exactness with perceptual boundaries?** Options:

1. **Post-process trim:** Run persistence for exact feature identification, then trim each detected climb to remove low-gradient lead-in/lead-out. This preserves the topological backbone but adjusts presentation boundaries. Risk: the trimming itself requires a gradient threshold (reintroducing a parameter) and may interact badly with the merge tree (child boundaries must nest within parent boundaries).

2. **Gradient-gate the birth/death:** Instead of using the absolute local minimum as the birth point, walk forward from the minimum until the gradient exceeds some threshold (e.g., 2%). Similarly, walk backward from the peak. This gives "effective" boundaries. Risk: the gradient threshold is a tunable parameter, and walking along the gradient requires a window size (another parameter).

3. **Report both:** Emit both the topological boundary (for mathematical correctness, vault matching, and fingerprinting) and a "display" boundary (for the user-facing presentation). The signature uses the full topological extent; the UI shows the trimmed version. Risk: complexity, and the user might create a vault with display boundaries that don't match the matching boundaries.

4. **Let the merge tree handle it:** The flat lead-in is itself a feature in the persistence diagram (a very low-persistence feature, likely below the 3.0m noise floor). If the noise gate eliminates it, the parent climb's effective start moves to where the next surviving child begins. This might naturally solve the problem in many cases. But it depends on the geometry — a 200m flat section at river level doesn't create a persistence feature at all if there's no dip.

Is there a principled way to define "effective climb start" that doesn't reintroduce hand-tuning?

---

## Problem 3: Significance Score Presentation

### The issue

Our GPD significance score G is a continuous value in [0, 1], where:
- G = 0.33 → 1-in-10 rarity for this geographic area
- G = 0.67 → 1-in-100 rarity
- G = 1.00 → 1-in-1000 rarity

Cyclists think in **UCI-style climb categories**: Cat 4, Cat 3, Cat 2, Cat 1, HC (Hors Catégorie). These categories are based on a formula involving length and gradient, standardized for professional road racing.

Our significance score is fundamentally different from UCI categories — it measures **geographic rarity**, not **absolute difficulty**. A Cat 4 climb in the Netherlands might score G = 0.8 (very rare for the area) while a Cat 1 climb in the Alps might score G = 0.4 (not that unusual for the Alps).

This is a feature, not a bug — it's exactly the kind of terrain-aware fairness we're building. But it creates a presentation problem:

- If we show G scores alone, cyclists won't know what they mean.
- If we map G scores to Cat 4/3/2/1/HC labels, we're lying — a G = 0.8 in the Netherlands is NOT an HC climb by any physical definition.
- If we show both (Cat 3 by UCI standards, G = 0.8 locally), does the user understand the distinction?

### Our current code

We already have a UCI-style categorization function in `workout-parse/src/climb/types.rs`:

```rust
pub fn calculate_uci_category(&self) -> &'static str {
    let gain = self.vert_m;
    let gradient = self.avg_gradient_pct.unwrap_or(0.0);
    let distance_km = self.distance_m.unwrap_or(0.0) / 1000.0;
    let difficulty = gain * (1.0 + gradient / 10.0);

    if gain >= 1000.0 || (distance_km >= 7.0 && gradient >= 8.0) || difficulty >= 1500.0 {
        "HC"
    } else if gain >= 500.0 || (distance_km >= 5.0 && gradient >= 6.0) || difficulty >= 800.0 {
        "1"
    } else if gain >= 300.0 || (distance_km >= 3.0 && gradient >= 5.0) || difficulty >= 450.0 {
        "2"
    } else if gain >= 150.0 || (distance_km >= 2.0 && gradient >= 4.0) || difficulty >= 200.0 {
        "3"
    } else if (gain >= 50.0 && gradient >= 3.0) || difficulty >= 75.0 {
        "4"
    } else {
        "UC"  // Uncategorized
    }
}
```

### The question

**What's the right presentation layer for significance + difficulty?** Some directions:

1. **Two axes:** Show UCI category (absolute difficulty) AND significance score (local rarity) as separate metrics. "Cat 3 climb, top 5% in your area." Clear but requires educating users on two concepts.

2. **Significance-based categories:** Define our own category system based on G score (e.g., Bronze/Silver/Gold/Platinum or 1-5 stars). Advantage: decoupled from UCI which isn't our system. Disadvantage: yet another categorization for cyclists to learn.

3. **Percentile language:** "Harder than 92% of climbs in this area." Universally understood. But loses the GP distribution interpretation and might feel like a generic fitness app metric.

4. **Hybrid:** Show UCI category as the primary label (because cyclists already understand it), with significance as a modifier. "Cat 3 ★★★★" where stars represent local rarity. The climb is objectively a Cat 3, but it's a 4-star feature in its area.

This is ultimately a product/UX decision, but the mathematical framework needs to support whatever we choose. Does the GPD output give us what we need for all of these options?

---

## Problem 4: FABDEM Bootstrap and Cold Start

### The issue

The GPD significance scoring requires precomputed terrain statistics per H3 resolution-5 cell (~253 km²). The bootstrap process:

1. Extract OSM road network polylines within the cell
2. Sample elevation profiles along roads from FABDEM (30m DEM)
3. Run 0D persistence on each road segment
4. Collect all persistence values above the noise floor
5. Fit GPD (threshold selection + PWM estimation)
6. Store: threshold u, shape ξ, scale σ, sample sizes, diagnostics

**Estimated cost:** ~8MB compressed for global coverage. ~$5-10 compute. ~11 hours single-machine.

**The cold-start problem:** Until this bootstrap runs for a given cell, we have no GPD parameters. A user rides in an un-bootstrapped cell and we can't score significance.

More subtly: **which roads matter?** OSM road coverage varies enormously. In Western Europe, nearly every farm track is mapped. In rural Africa or South America, major highways might be the only mapped roads. The GPD fit for a cell depends on which roads were sampled — if only highways are mapped, the distribution will underestimate terrain variability (highways avoid steep grades).

**The update problem:** Terrain doesn't change (fast), but OSM improves continuously. When new roads are mapped, the GPD parameters should be updated. How frequently? Is the old fit "wrong" or just "less complete"? Do significance scores for existing vaults need to be recomputed?

### The question

**What's the right bootstrap strategy?**

- **Minimum viable:** Bootstrap the cells that our actual riders are in (start with a few hundred cells, expand as ridership grows). Use a fallback scoring method (e.g., the UCI formula above, or a simple vert-based percentile) for un-bootstrapped cells.
- **Full global:** Run the full bootstrap before launch. 8MB and $10 is trivial. But quality varies with OSM coverage.
- **Hybrid:** Full global bootstrap using a coarser grid (H3 res-4, ~1,770 km²) for areas with sparse OSM, full res-5 for areas with good coverage. Use the coarser cell as a prior when the fine cell has insufficient data.

And: **should we supplement OSM roads with raw DEM ridge/valley extraction?** Running persistence directly on the DEM raster (not just along roads) would capture terrain features independent of road mapping. This makes the GPD more robust in poorly-mapped areas, but includes off-road terrain that cyclists will never encounter.

---

## Problem 5: The Discrete Classification Gap (Why We're Doing All This)

### The current system

Our v1 detector classifies each ride into one of 4 terrain categories, then applies category-specific thresholds:

| Category | min_vert | min_gradient | min_duration | VAM_min | drop_tolerance |
|----------|---------|-------------|-------------|---------|---------------|
| Flat | 15m | 2.0% | 60s | 150 | 15m |
| Rolling | 25m | 2.5% | 60s | 200 | 16m |
| Hilly (default) | 50m | 4.0% | 120s | 300 | 30m |
| Mountainous | 100m | 5.0% | 180s | 400 | 50m |
| Urban Hills | 20m | 3.0% | 60s | 200 | 10m |

There are also 10 momentum model parameters per category (momentum_start_threshold, momentum_end_threshold, climb_rate, drain_rate, decay_rate, max, gradient_neutral). Total: ~18 parameters × 5 presets = **90 hand-tuned values**.

### Where it breaks

**Boundary problem:** A ride along the Norfolk coast that's 95% flat with one brutal 80m cliff climb. The terrain classifier sees mostly flat → applies flat thresholds → the cliff climb is detected but scored and treated as if flat-terrain features are the norm. There's no mechanism for "this ride is flat EXCEPT for one remarkable feature."

**Granularity problem:** The categories are too coarse. Real terrain is continuous. The boundary between "rolling" and "hilly" is arbitrary. A ride in the Cotswolds might classify as rolling on one day (long loops through valleys) and hilly on another (if the route crosses one big ridge), producing different climb detection results for the same geographic area.

**Context blindness:** The significance of a detected climb is independent of its surroundings. A 50m climb in flat Kansas and a 50m climb in the rolling Cotswolds receive identical treatment if both rides classify as "rolling." The v1 system has no mechanism for geographic context.

**Parameter fragility:** The 90 hand-tuned values were calibrated against a small set of test rides. They work for the terrain types the developer tested. They may not work for terrain types nobody tested — coastal clifftop roads, volcanic island climbs, high-altitude plateau riding, urban rides with bridge climbs.

### What v2 solves

The persistence + GPD architecture eliminates ALL of these problems by construction:

- **No classification step:** Every feature is found at every scale, no thresholds needed for detection.
- **Continuous context:** GPD shape parameter ξ smoothly captures terrain character (mountainous=heavy tail, flat=bounded) without discrete categories.
- **Per-feature scoring:** Each climb is scored individually against its local geographic distribution, not against a ride-level classification.
- **Zero detection parameters:** The persistence computation is parameter-free. The noise floor is derived from sensor physics. The GPD is fitted to geographic data.

### What v2 might not solve

The discrete classification gap is gone, but a subtler version of the problem might remain:

1. **H3 cell boundaries:** Our GPD is fitted per H3 res-5 cell. A ride that crosses a cell boundary (common — cells are ~9km wide) will have climbs scored against different GPD parameters on either side. A long climb spanning two cells has its start scored against one distribution and its summit against another. How do we handle cross-cell climbs?

2. **Micro-terrain variation within a cell:** A 250 km² cell is large. It might contain both a river valley (flat) and a mountain ridge (steep). The cell-level GPD is a blend of both, which dilutes the significance of features in either sub-region. Is res-5 the right granularity?

3. **The "unique feature" problem** the user identified: A single remarkable feature in otherwise unremarkable terrain. The cell-level GPD will have most features clustered at low persistence values, with one outlier. The GPD should handle this (it's literally what extreme value theory is for), but the small number of tail observations means high uncertainty. Is the scoring robust enough to correctly identify "this is the one interesting thing here"?

4. **Temporal stability:** If we update GPD parameters as more road data is mapped, significance scores change. A vault that was "top 5% in the area" might become "top 8%" when new roads are added to the bootstrap. For an economic system where vault value depends on significance, this instability could be problematic.

---

## Summary of Questions

| # | Problem | Core Question |
|---|---------|---------------|
| 1 | Barometric drift | Should we DEM-correct elevation before persistence, or handle drift downstream? |
| 2 | Boundary perception | How do we give users intuitive climb start/end without reintroducing hand-tuned parameters? |
| 3 | Score presentation | How do we present continuous geographic significance alongside absolute difficulty? |
| 4 | Cold start | What's the right bootstrap strategy given variable OSM coverage? DEM-only as supplement? |
| 5 | Residual gaps | Cross-cell climbs, within-cell variation, unique feature detection, temporal stability |

---

## References

- **Full v2 spec:** `docs/CLIMB_DETECTION_V2_SPEC.md`
- **Current v1 detector:** `workout-parse/src/climb/detector.rs`
- **Current v1 signatures:** `workout-parse/src/climb/signature.rs` (SHA256 gradient hash, 64-byte format)
- **Current v1 terrain presets:** `workout-parse/src/climb/types.rs` (5 presets × 18 params)
- **Plain English summary:** `docs/THE_HILL_KNOWS_ITS_OWN_NAME.md`
- **Product context:** Climb vaults are on-chain economic objects. Detection accuracy, scoring fairness, and signature stability directly affect token distribution and user trust.
