# Next Implementation Tasks

> **Canonical detector parameters:** See `docs/DETECTOR_PARAMS.md` for current production values.

**Current state:** P=74.4%, R=81.1%, F1=0.776 (holdout, 131 eval rides)
**Target:** P>=82%, R>=80%, F1>=0.80

## Completed Heuristics

- [x] **H2** — Power Confirmation (`_h2_power_confirmation_bonus`, range [-1.0, +1.5])
- [x] **H3** — Terrain Context (`_h3_terrain_context_bonus`, range [-3.0, +3.0])
- [x] **H4** — Intensity Score (`_h4_intensity_bonus`, range [0, +3.0], top tier 50K)
- [x] **H9** — Roller Filter (`_h9_roller_filter_bonus`, range [-2.0, 0], 90s cutoff)
- [x] **H10** — Topographic Isolation (`_h10_isolation_bonus`, range [-1.5, +2.0])
- [x] **H12** — Frequency Prior (`_h12_frequency_prior_bonus`, range [0, +1.0], capped)

## Task 1: Evaluation Hygiene (Professor Review Fixes)

**What:** Fix three methodological issues identified in April 2026 code review:
1. H12 frequency map leakage — holdout uses full-corpus map (train/eval leakage)
2. Geo eval asymmetry — SEPA gets frequency prior, other geos don't
3. Bridge preprocessing gap — eval runner skips `preprocess_bridge_elevations()`

**Why:** Our reported metrics may be slightly inflated. We need honest numbers before claiming generalization.

**Deliverable:** Two score modes: `scientific_holdout` (H12 off) and `deployment_holdout` (full production pipeline).

## Task 2: H11 — Gradient Consistency Filter

**What:** Score based on gradient variance within the climb. Steady climbs (low variance) are more segment-worthy than choppy terrain at the same average gradient.

**Why:** "A steady 6% climb is perceived as more segment-worthy than alternating 2%/10% at the same average." This separates real climbs from rolling terrain false positives.

**Integration:** Compute gradient stddev from tile_samples within the climb's time window. Low stddev = bonus. High stddev = penalty.

**Expected impact:** +1-2% precision.

## Task 3: H1 — Road Identity Integration

**What:** Wire existing OSM road enrichment data into the chooser as a scoring heuristic. Named climbing roads get a bonus; unnamed/service roads get a penalty.

**Why:** Strongest road-context signal from road features research. Data already exists (`road_name`, `road_coverage_pct` on `patterns_climb`). Needs to be available during scoring, not only after detection.

**Challenge:** Road enrichment currently runs AFTER detection in `pattern_engine.py`. Need to pre-compute road features from tile_samples during the canonical_v2 path.

**Expected impact:** +2-4% recall (named climbing roads boosted), +1% precision.

## Task 4: Ground Truth Cleanup

**What:** Audit top 50 "extras" — real climbs without Strava segments vs actual false positives. Reclassify and compute corrected metrics.

**Why:** ~34% of extras have vert>=30m AND grade>=3% — probably real climbs. Cleaning ground truth may reveal true precision is higher than measured.

## Task 5: Re-run Parameter Sweep

**What:** After H11 and ground truth cleanup, re-run sweep to check for parameter interactions. Only worthwhile if a new signal (H11, H1, or label cleanup) is added.

**Why:** Latest sweep (tools/corpus/sweep_results_b3bdcfb1.csv) shows best combo is only ~0.00025 F1 better than production. Further micro-tuning without new signals is statistical dust.

## Sequencing

```
Task 1 (eval hygiene) → honest baseline numbers
    ↓
Task 2 (H11 gradient consistency) → corpus run → commit
    ↓
Task 3 (H1 road identity) → corpus run → commit
    ↓
Task 4 (ground truth cleanup) → corrected metrics
    ↓
Task 5 (parameter sweep) → only if new signal warrants it
```

## Strategic Notes

- **Recall-forward:** Missing a real climb is worse than detecting an extra. Many "extras" are real climbs without Strava segments.
- **Next real levers** are H11, H1 road identity, and label cleanup (per Professor review). Not parameter micro-tuning.
- **90s roller cutoff (H9)** and **50K intensity top tier (H4)** were resolved in the March 2026 full-resolution recalibration.
