Corpus Workflow

`tools/corpus/` is the offline evaluation stack for climb-detection work. The intent is:

1. Process a large real-world export into a frozen SQLite corpus.
2. Generate benchmark scorecards and audits from that corpus.
3. Curate a smaller golden subset for manual review and regression testing.

Recommended flow

```bash
# 1. Process a Strava export into a SQLite corpus
python tools/corpus/process_corpus.py \
  /Users/gabetemp/Downloads/export_440100/activities \
  --csv /Users/gabetemp/Downloads/export_440100/activities.csv \
  --db tools/corpus/export_440100.db \
  --resume \
  --v1

# 2. Generate a seed manifest for manual curation
python tools/corpus/build_golden_manifest.py \
  /Users/gabetemp/Downloads/export_440100 \
  --corpus-db tools/corpus/export_440100.db \
  --output /tmp/export_440100_seed_manifest.json

# 3. Review the seed manifest and annotate the best benchmark rides
#    - negative controls (no real climbs)
#    - rolling terrain
#    - hilly / urban walls
#    - mountainous
#    - source-format parity (fit vs gpx vs tcx)

# 4. Promote a small hand-annotated subset into tests/validation/
#    and update tests/validation/manifest.json when the rides are stable.
```

Visual review loop

Once a ride is in `tests/validation/` or exists as a live BR ride, generate an
HTML review report before changing detector thresholds blindly:

```bash
# Friendly wrapper: ride UUID, validation file, or local file.
python3 scripts/review_climb.py t_h_e_w_a_l_l.fit
python3 scripts/review_climb.py 1d129d39-f2da-46c0-94d6-73726cb5b536 --terrain rolling

# Under the hood, the wrapper calls the raw renderer:

# Validation fixture
python3 tests/validation/render_climb_review.py \
  --validation-file in_the_bag_.fit \
  --output /tmp/in_the_bag.climb-review.html

# Live ride (requires backend env + storage access)
set -a
source backend/.env
set +a
python3 tests/validation/render_climb_review.py \
  --ride-id 1d129d39-f2da-46c0-94d6-73726cb5b536 \
  --terrain rolling \
  --output /tmp/live-ride-review.html
```

The report shows:

- the elevation profile with persistence and canonical overlays
- a terrain sweep for momentum presets, which canonical currently chooses among
- a review table that flags suspicious persistence segments against canonical anchors
- expected-climb anchors when they exist in the manifest

Candidate-generator scorecard

When changing the canonical climb path, run the corpus comparison before
changing defaults:

```bash
python3 tests/validation/compare_candidate_generators.py
```

This scorecard compares `persistence`, `momentum_auto`, `momentum_hilly`, and
the current `canonical`/`canonical_v2` chooser against the annotated FIT
validation manifest. It emits the failure taxonomy used for detector tuning:
clean passes, false positives on negative controls, under-detection,
over-generation, mixed boundary drift, and weak/pending annotation anchors.

Golden Strava holdout

The Strava-import benchmark uses cached activity streams in
`tools/corpus/golden_corpus.db` plus the frozen `ride_split` table. Run both
product-relevant sample modes before making detector decisions:

```bash
# Fast local smoke run
python3 tools/corpus/run_holdout_eval.py --mode both --limit 5 --output /tmp/br_holdout_smoke.json

# Full current benchmark
python3 tools/corpus/run_holdout_eval.py --mode both --output tools/corpus/holdout_results.json
```

`scientific` mode disables the H12 frequency prior and bridge preprocessing for
an honest no-leakage baseline. `deployment` mode uses the production pipeline
(H12 + bridge preprocessing). The JSON output includes per-ride failure
taxonomy so tuning work can separate over-generation, under-detection, and mixed
boundary drift instead of relying on aggregate F1 alone.

Compare two saved holdout runs before keeping a detector change:

```bash
python3 tools/corpus/diff_holdout_runs.py \
  /tmp/br_h12_current_deployment.json \
  /tmp/br_experiment_deployment.json \
  --mode deployment \
  --json-output /tmp/br_experiment_diff.json
```

The diff report ranks changed rides by metric damage or gain, which makes a
prototype reviewable even after reverting the code.

Drill into the changed rides at segment/detection level:

```bash
python3 tools/corpus/explain_holdout_activity.py \
  2243288124 140119888 \
  --mode deployment \
  --output /tmp/br_changed_rides_drilldown.json
```

The drilldown uses the same deployment/scientific scoring path as the holdout
run and emits matched, missed, and extra rows with boundary offsets.

Audit bridge preprocessing as an upstream signal edit:

```bash
python3 tools/corpus/audit_bridge_preprocessing.py \
  --split eval \
  --output /tmp/br_bridge_preprocessing_audit.json
```

The bridge audit scores each ride with the deployment frequency map and bridge
preprocessing off/on, then writes accepted and skipped bridge spans with sample,
time, track-distance, and bridge-length diagnostics.

Trace the detector pipeline for one or more rides:

```bash
python3 tools/corpus/trace_detector_pipeline.py \
  4110512700 3034853752 \
  --bridge-mode both \
  --output /tmp/br_detector_trace.json
```

The trace harness records stream quality, bridge elevation deltas, generated
momentum/persistence candidates, canonical_v2 cluster scoring, selected
detections, match rows, and missed/extra diagnosis buckets. Use it before
changing core detector thresholds.

Shoulder-miss miner

When the product problem is specifically "canonical starts earlier on a real
climb, persistence snaps to a later inner core", mine a corpus pack first
instead of tuning on a single ride:

```bash
python3 tools/corpus/find_shoulder_cases.py \
  --db tools/corpus/corpus.db \
  --export-root /Users/gabetemp/Downloads/export_440100/activities \
  --limit 6 \
  --render-top 3 \
  --output /tmp/shoulder_cases.json
```

This produces:

- a ranked JSON list of similar failure cases
- the persistence/canonical count gap and start-delay evidence for each case
- local HTML review reports for the top rendered cases

Design principles

- Keep the large corpus external to git.
- Keep benchmark manifests in git once they are curated and stable.
- Prefer a small hand-reviewed golden set over a huge weakly-labeled set.
- Track both source fidelity and detector output:
  - original file format (`fit`, `gpx`, `tcx`)
  - whether the ride has power / HR
  - terrain class from the offline corpus
  - climb counts and obvious failure patterns

Recommended golden-set composition

- 5-10 negative controls
- 10-15 rolling rides
- 10-15 hilly / urban-wall rides
- 5-10 mountainous rides
- 5-10 cross-source parity cases

The goal is not just “lots of rides.” The goal is a benchmark set that catches:

- umbrella parent climbs
- nested climb spam
- false positives on flat rides
- missed short steep climbs
- directionality errors
- source-format sensitivity
