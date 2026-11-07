# RFC: Canonical V2 Climb Truth Engine

**Status:** Implemented first slice  
**Date:** 2026-03-19

## Why

The repo now has multiple useful climb proposal sources:

- momentum terrain sweeps
- persistence/topology
- road-aware post-processing

Treating any one of those as ground truth creates detector civil war. The right
shape is one truth engine that evaluates many proposals on one shared product
path.

`canonical_v2` is that first step.

## Goals

- Keep one product truth engine.
- Let momentum and persistence contribute evidence without fighting.
- Penalize sparse/imported/noisy rides instead of pretending all devices are equal.
- Prefer abstention or conservative selection over optimistic over-showing.

## Non-Goals

- Full route-distance map matching.
- DEM/barometer fusion.
- Canonical climb inventory consensus updates across many rides.
- Replacing the review corpus with an ML model.

Those are later phases.

## Architecture

### 1. Shared Ride Quality Profile

Each ride gets a `RideQualityProfile` derived from the existing sensor-integrity
layer. It captures:

- source class
- integrity score
- GPS coverage
- elevation coverage
- sampling regularity
- gap ratio
- sparse/degraded flags

This makes source quality a model input rather than an afterthought.

### 2. Proposal Sources

`canonical_v2` currently uses:

- momentum proposals from `auto`, `hilly`, and `urban_hills`
- persistence proposals from raw candidate samples when available

### 3. Conservative Chooser

The chooser works in two stages:

1. Pick a single momentum baseline terrain set using:
   - existing terrain-set strength scoring
   - penalties for fragmented low-grade drags
   - limited corroboration bonus from persistence

2. Let persistence modify that baseline conservatively:
   - override a baseline climb only when materially better
   - add a persistence-only climb only when corroborated by multiple momentum terrains
   - reject low-confidence marginal proposals on sparse/degraded rides

This keeps one baseline truth path while still learning from persistence.

## Current Scoring Shape

Per-candidate score is:

`strength + source_prior + corroboration_bonus - fragmentation_penalty - quality_penalty`

Important penalties:

- long low-grade drags
- tiny/short fragmented efforts
- sparse sampling
- degraded GPS/elevation coverage

Important bonuses:

- cross-family corroboration
- strong persistence evidence
- stable momentum terrain source

## Current Outcome

On the current validation corpus, the first `canonical_v2` slice scores:

- `momentum_auto`: `23`
- `canonical_v2`: `19`
- `canonical`: `16`
- `persistence`: `5`

Interpretation:

- `canonical_v2` is better than the old production `canonical` path
- it is still not the best overall generator on the current corpus
- it is intentionally more conservative, with fewer extras and more misses

That is acceptable for now because the product risk is false public truth, not
missing a marginal climb on a single ride.

## Default Policy

`PatternEngine` now defaults to `CLIMB_ALGORITHM=canonical_v2`.

This promotes the improved conservative chooser without claiming the climb
problem is solved.

## Next Phase

The next meaningful upgrades are not more selector micro-tuning. They are:

1. Route-aligned profile
   - map matching
   - distance-along-route climb windows

2. Better elevation truth
   - DEM correction
   - barometer/GNSS reconciliation

3. Canonical inventory consensus
   - many-ride support
   - cross-device weighting
   - stable public climb boundaries

4. Stronger benchmark slices
   - imported GPX fidelity
   - sparse rides
   - bridges/tunnels
   - rolling shoulder cases

## Repo Impact

Primary implementation lives in:

- `backend/app/services/patterns/climb.py`
- `backend/app/services/pattern_engine.py`
- `tests/validation/compare_candidate_generators.py`
- `backend/tests/services/patterns/test_climb_canonical.py`
