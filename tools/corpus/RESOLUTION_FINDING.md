# Data Resolution Finding (2026-03-22)

## Discovery

The detector has been running on `tile_runs` (H3 tile-aggregated data) instead of `tile_samples` (per-second raw data). tile_runs compress the elevation signal by **7.2x** — a typical ride has 11,355 raw samples but only 1,583 tile runs.

In a 60-second climb window:
- **tile_samples:** ~60 elevation points (full detail)
- **tile_runs:** ~8 elevation points (heavily averaged)

Short steep climbs (30-60 seconds, <500m) get averaged away in tile_runs. The gradient transitions that mark climb onset/end are smoothed out.

## Impact

Running the detector on tile_samples instead of tile_runs:
- **Recall: +11.2pp** (71.3% → 82.5% on 500/538 rides)
- **Precision: -8.0pp** (80.5% → 72.5%)
- **F1: +1.6pp** (0.756 → 0.772)

The recall gain is massive — comparable to the multi-terrain merge (6.8pp) and the entire heuristic tuning phase combined. The precision drop is expected: more data = more signal AND more noise.

## Implications

1. **All prior parameter tuning was optimizing against a data bottleneck.** The chooser was tuned on coarse data. Optimal thresholds on full-resolution data will be different.

2. **The parameter sweep needs re-running on full-resolution proposals.** Cached proposals were built from tile_runs. Need to rebuild with tile_samples.

3. **The heuristics (H3/H4/H9) were recalibrated (2026-03-21).** H9 duration cutoff raised from 60s to 90s, H4 top tier raised from 30K to 50K. See `docs/DETECTOR_PARAMS.md` for current values.

4. **Template matching is unaffected** — it uses GPS corridors, not elevation data.

5. **Production ride processing** uses tile_runs by default. To deploy this improvement, the ride processing pipeline needs to pass tile_samples to the detector. The Rust detector can handle the higher volume — it's O(n log n) for persistence.

## Action Items

1. Re-cache proposals with tile_samples: modify `parameter_sweep.py` to use tile_samples
2. Re-sweep on full-res proposals to find optimal params for the new data shape
3. Run the honest temporal split evaluation with full-res detector + templates
4. Update production `ride_processor.py` to pass tile_samples to detect_climbs_with_rust

## Production Consideration

tile_runs exist for a reason — they're used for tile territory tracking, H3-based vault matching, and spatial queries. The detector doesn't NEED to use tile_runs just because they exist. The fix is: compute tile_runs for spatial purposes, compute tile_samples for detection, pass each to the appropriate consumer.
