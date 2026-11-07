# Workout parser torture corpus

This corpus is a permanent, fully synthetic input-robustness contract for
`workout-parse`. It contains no rider data. Each case is listed in
`manifest.json`, locked by SHA-256, and exercised as an individual Rust test
in `workout-parse/tests/torture_corpus.rs` through both explicit-type and
automatic dispatch. No Python-binding or
`backend/app/services/workout_parse_adapter.py` replay exists yet; the Rust
harness is the only executable form of this contract today.

The expected outcomes deliberately distinguish parsing from later ride
integrity policy:

- Malformed structure, invalid coordinate encodings, impossible clock domains,
  unsupported unit declarations, and truncated inputs reject the whole source.
- Syntactically valid device testimony such as a teleport, impossible implied
  speed, altitude spike, duplicate timestamp, sensor gap, Null Island (0,0)
  fix, or an out-of-range coordinate that is still exactly representable in
  e7 is preserved exactly. The parser never smooths, sorts, interpolates, or
  fabricates a replacement; the ratified per-sample gates downstream
  (TRUTH_CONTRACT INV-DATA-1: `is_valid_gps`, sensor integrity) abstain on
  that evidence.
- A value the e7/i32 representation cannot hold exactly must reject rather
  than saturate into a coordinate the device never reported.
- Missing elevation and sensor values remain missing. Zero remains valid where
  the format defines it as a real measurement.

Ten reject cases assert doctrine the shipping parser does not yet enforce;
their tests are `#[ignore]`d with reasons naming the parser-defect findings
recorded on bead boulderroller-v2-8pac2 (run them with
`cargo test --test torture_corpus -- --ignored`). Fixing a defect means
removing its `#[ignore]`, never weakening the assertion.

Coverage includes truncated and corrupted FIT, GPS pathologies, DST and offset
transitions, Wahoo/Garmin/Hammerhead/Apple-Watch/phone-shaped field layouts,
developer-field noise, unit/encoding traps, empty streams, and a small gzip
fixture whose declared expansion exceeds the 100 MiB input limit.

Regenerate from the repository root with:

```text
python3 workout-parse/tests/fixtures/torture/generate_corpus.py
```

Regeneration is deterministic. Review both `manifest.json` and the generated
binary diffs before committing changes.
