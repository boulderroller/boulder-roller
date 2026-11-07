# Holdout Dispute Review - 2026-04-29 canonical_v2

Source scorecard:

- DB: `/tmp/br_golden_corpus_eval_full_floor.db`
- Run: `canonical_v2_20260429_210311_85714d`
- Rides scored: 660
- Aggregate: matched 3110, missed 1081, extras 827, precision 0.7899, recall 0.7421, F1 0.7653

Generated HTML review reports live in the ignored local directory:

`tools/corpus/reviews/holdout_disputes_20260429/`

Regenerate one report with:

```bash
python3 tools/corpus/generate_ride_review.py \
  --db /tmp/br_golden_corpus_eval_full_floor.db \
  --run-id canonical_v2_20260429_210311_85714d \
  --output-dir tools/corpus/reviews/holdout_disputes_20260429 \
  --activity-id <activity_id>
```

## Reviewed Cases

| Activity | Ride | Signal | Review call |
| --- | --- | --- | --- |
| `709103855` | Afternoon Ride | 29 missed, 0 matched, 0 extras. Every missed row is the same `Dtown Mountain` segment: 28m at 2.3% over 1230m, repeated across the ride. | Benchmark label spam / weak Strava segment truth. Do not tune detector against this as a climb miss. |
| `607605223` | Lunch Ride | 18 missed, 0 matched, 0 extras. Every missed row is `County Road 635 Climb`: 122.6m at 16.9% over 727m, repeated every few minutes. | Segment-effort/template noise or stream-index mismatch. Treat as holdout label defect until independently verified. |
| `324712314` | 06/13/2015 Pitman, New Jersey | 16 missed, 0 matched, 0 extras. Same repeated `County Road 635 Climb` pattern as `607605223`. | Same benchmark defect class as above. |
| `3523251381` | WISSAHICKON 100 | 22 matched, 25 missed, 9 extras. Misses are repeated small urban climbs (`Double Climb`, `Full Gorgas Climb`, `Henry Ave.`, `Hammer to the Gravel`, `Hortter climb`), mostly 25-44m. Extras are nearby 24-55m urban-hill detections. | Reviewed as `urban_repeat_policy_review` in `tools/corpus/policy_reviews/3523251381_urban_repeat_policy.html`. Product-visible misses are limited to steep/sustained urban-punch climbs; shallow/moderate 25-36m repeats are benchmark-only and should not tune broad detector thresholds. |
| `137486081` | Gila 1,2 Stage 5 | 7 matched, 1 missed, 10 extras. Extras include large plausible mountain efforts, including 340m, 156.8m, 113m, 87.9m, and several 36-66m climbs. | Likely Strava label coverage gap. These should be reviewed as unlabeled real climbs, not blindly suppressed. |
| `3175139947` | light work in the mountains | 8 matched, 0 missed, 9 extras. Extras include 456.8m, 189.3m, 63.2m, 62.3m, and several 33-50m efforts. | Likely Strava label coverage gap. Detector is finding plausible climbs beyond segment ground truth. |
| `3167162114` | Lunch Ride | 8 matched, 0 missed, 8 extras. Extras include 416.2m, 196m, 69m, 67.5m, 66.1m, and smaller efforts. | Likely Strava label coverage gap. Treat extras as review candidates, not automatic false positives. |
| `106188671` | Close to the Edge | 10 matched, 2 missed, 7 extras. Extras include 342.1m, 99.6m, 78.6m, and smaller climbs; misses average 37.4m at 3.5%. | Mostly label coverage gap, with minor small-climb misses below the main product signal. |

## Follow-ups Filed

- `boulderroller-v2-z05b`: repeated segment-effort spam in Strava holdout scoring. `Dtown Mountain` and `County Road 635 Climb` dominate top misses without matching detector evidence.
- `boulderroller-v2-81wl`: WISSAHICKON 100 urban-repeat policy review. Smaller HTML policy pack generated at `tools/corpus/policy_reviews/3523251381_urban_repeat_policy.html`; holdout taxonomy now labels the ride `urban_repeat_policy_review`.

## Decision

Do not use the broad Strava holdout aggregate as a blind threshold target. The top dispute pack splits into:

- repeated/stale segment-label defects that should be filtered or quarantined in the holdout scorer;
- mountain extras that are plausibly real unlabeled climbs;
- one urban-repeat case (`3523251381`) that is now classified as a policy lane instead of a generic detector miss cluster.

The committed FIT validation manifest remains the hand-reviewed local fixture truth. The Strava holdout remains useful for mining candidate cases and regression pressure, but not as direct product truth without curation.
