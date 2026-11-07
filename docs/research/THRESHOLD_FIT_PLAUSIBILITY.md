# Threshold plausibility exploratory calibration, 2026-09-24

Recommended provisional review predicates: fitted CP / E180 < 0.25 OR fitted W' > 60,000 J. Equality passes each predicate. This is a deliberately permissive review policy, not a physiological law and not a replacement for the time-implied floor. The 0.25 floor allows CP to be as little as one quarter of the three-minute maximum; the cap is more than twice the approximately 27–29 kJ means reported in the cited team-pursuit cohorts. Neither literature cohort establishes a universal tail bound.

## Local evidence

Read-only source: tools/corpus/golden_corpus.db; SHA256 64b15790bed2628b3e7e8371657b408ec5e96305db84bfe050507b14860b98ee. Source HEAD 807986f0e7d0c34690c3afc0aa749cf1fd04a5fd; metrics.rs SHA256 0fbfa6d61796ee999a03284ec2869ed574eb8f7b45f99829452ad0a646214e0b. Canonical Rust compute_mean_max_power_series freshly built from that checkout; no substitute resampling/rolling arithmetic. Its Python package wrapper does not export that function, so script imports from workout_parse.workout_parse.

1416 stream records; 480 carry watts. Power records span 2012-09-22 to 2018-02-23. Six records fail canonical extraction because their activity span exceeds the canonical 172,800-second duration limit; six further records lack complete 15-minute anchors. The remaining 468 each produce positive CP and W' within the already-existing 50–500 W CP bounds. Treating each as a hypothetical first fit, all 468 pass the proposed two predicates: 0/468 observed added review flags (0%). This is NOT a validated false-positive rate: no honest/attack labels, no iOS attestation, no verified maximal efforts, and no independent rider identifiers.

Individual fit range: CP/E180 0.300320626–0.988965969, W' 734–52,689.798077 J. A 0.30 floor leaves only 0.000320626 headroom at the observed minimum; 0.25 provides broader margin. A 50,000 J cap flags 6/468 (1.282%), a 40,000 J cap 24/468 (5.128%). At 60,000 J, raising the floor to 0.35 flags 4/468 (0.855%) and to 0.40 flags 13/468 (2.778%). Thresholds were selected using this dataset; zero observed flags is therefore in-sample exploratory evidence, not out-of-sample validation.

The database contains no rider identifier. A corpus-wide chronological pooled envelope is therefore only a sensitivity exercise, NOT a reconstruction of identified riders' establishments. It produces 19 distinct changed complete in-bounds envelopes. All 19 pass proposed predicates; lowest ratio 0.475517838, highest W' 40,407.567308 J.

The supplied degenerate exact anchors (400, 205.714285714..., 128) fit CP 60 W, W' 61,200 J and CP/E180 0.15: both predicates flag. Honest anchors (400,300,270) fit CP 233.814103 W, W' 29,682.692308 J and ratio 0.5845352575: pass, rounded Threshold 234 W.

## Why no standalone collinearity predicate

The existing model is precisely P(t)=CP+W'/t. Exact collinearity in P versus 1/t is what an ideal valid two-parameter critical-power model predicts. Rejecting it would reject a perfect model fit. Near-collinearity is observed naturally in this dataset: 5/468 have max absolute residual <=0.1 W and 60/468 <=1 W. No evidence here supports a lower residual rejection threshold. Thus no collinearity constant is proposed. As a focused counterexample, ideal collinear anchors from CP=200 W and W'=18,000 J (300, 242.857142857..., 220) should pass: CP/E180=2/3 and W'=18,000 J. The power-shape ratio and W' review cap catch the supplied degenerate profile while allowing well-proportioned exact model fits.

## Primary literature and limits

- Clark & Macdermid (2021), A comparative analysis of critical power models in elite road cyclists. https://pmc.ncbi.nlm.nih.gov/articles/PMC8562202/ (author university copy https://mro.massey.ac.nz/server/api/core/bitstreams/a4633032-80c7-4602-8c23-d55b59610e04/content). Explicitly gives Linear-P equation PO=W'*(1/t)+CP and reports meaningful model-dependent CP/W' differences. Supports omitting a standalone collinearity rejection and treating fit parameters cautiously.
- Critical power, work capacity, and recovery characteristics of team-pursuit cyclists (2022). https://repository.lboro.ac.uk/articles/journal_contribution/Critical_power_work_capacity_and_recovery_characteristics_of_team-pursuit_cyclists/22263583 . International/national/regional pursuit cohorts report W' means 27.2, 29.3 and 28.8 kJ, respectively. A 60 kJ review cap is intentionally well above these cohort means. These means do not define a biological maximum or establish coverage of sprint athletes, women, para athletes or children.
- Chorley et al., Physiological and anthropometric determinants of critical power, W' and the reconstitution of W' in trained and untrained male cyclists (2020). Author manuscript https://hira.hope.ac.uk/3287/1/Study2_CorrelationAnalysis__PlainText_v7.01_expandedrefs.pdf . n=20, combined CP 268±43 W and W' 11.0±4.0 kJ; trained n=9 W'12.7±3.4 kJ; untrained n=11 W'9.6±4.1 kJ. Small male cohorts are context, not universal bounds.

Ratification/change bar for either constant: Tim ratification; larger rider-linked power corpus with known establishments, representative body sizes/disciplines, adjudicated honest/flagged profiles, and review outcomes; rerun boundary/regression tests and report changes in held-pay incidence before any deployment. Review must retain held pay, not reject it permanently.

## Reproduce

```sh
CARGO_TARGET_DIR=/tmp/threshold-calibration-target maturin build --manifest-path workout-parse/Cargo.toml --features python --interpreter /usr/bin/python3 --out /tmp/threshold-calibration-wheels
unzip -o -q /tmp/threshold-calibration-wheels/workout_parse-0.1.0-cp39-cp39-macosx_11_0_arm64.whl -d /tmp/threshold-calibration-module
PYTHONPATH=/tmp/threshold-calibration-module python3 tools/corpus/calibrate_threshold_fit.py --corpus-db tools/corpus/golden_corpus.db --output /tmp/threshold-calibration-results.json
```

The script prints aggregates only and includes no private activity IDs, names or coordinates.

## Implementation boundary

Migration 165 and its backend Supabase mirror share one private SQL predicate.
New eligible profiles failing it use the existing `below_bounds_review` path.
Raw effort and candidate evidence remains append-only; rejected fits do not
advance the economic candidate. Plausible new evidence can establish/raise the
Threshold without deleting the retained review. Economic authority never goes
down. Sealing rechecks both the submitting fit and the fit behind its lifetime
maximum; a migration preflight refuses existing bad cached, pending or sealed economic
authority atomically, because its safe correction is outside this brief. New release
batches and snapshots recheck the same authority before any new child release.
The planner persists SQLSTATE `BRR07` as repairable review, never `not_counted`.

This migration neither rewrites sealed authority nor revokes an already-frozen
release or on-chain authorization. Those require the separate correctable
Threshold rule. Legacy initialization inherits previously verified authority
with no fitted anchors, as already ratified; no fit is invented for it. The
existing 16-week held eligibility rule is unchanged; this gate adds no forfeiture
or extension. Review alone is not proof that a profile is malicious. The gate
catches the supplied attack but does not establish maximal effort or prevent
all sandbagged profiles (for example higher easy-power values can pass both
limits). The time-implied floor remains a separate gated defense.

Local PostgreSQL tests exercise fit boundaries, exact/rounded attack anchors,
honest 234 W sealing, raises, retained economic maxima, atomic refusal of pre-migration bad economic
state, held release wait/recovery, private helpers and release review
routing. Historical corpus verification uses the same canonical mean-max Rust
code and compares all complete fits against PostgreSQL's actual fit and gate.

Concrete residual attack: P=400 W followed by e=100 W gives CP=100 W,
W'=54,000 J, and CP/E180=0.25, which passes these conservative bounds. Relative
to sealed 234 W, same-power pay is still 5.4756 times greater. No claim is made
that this gate eliminates the entire degenerate-profile family.

Migration concurrency: write-conflicting table locks precede the preflight and
remain until commit. A candidate-insertion guard aborts an in-flight old
registration body with retryable SQLSTATE `40001` if it resumes after migration
and attempts to accept an implausible fit. Its retry uses the new registration
policy and retains the profile for review.
