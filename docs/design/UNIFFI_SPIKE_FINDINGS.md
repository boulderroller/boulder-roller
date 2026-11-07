# UniFFI Swift Binding Spike — Findings

**Bead:** `boulderroller-v2-8mp46` · **Branch:** `claude/boulderroller-v2-8mp46-uniffi-spike` · **Date:** 2026-08-09
**Status:** Spike complete. All four acceptance criteria met, including the on-simulator run (the macOS fallback was not needed).

## What this proves

The real `workout-parse/` Rust crate binds to Swift through UniFFI, and a ride
parsed on an iOS simulator produces **byte-identical** canonical hash, NP/TSS/IF,
and H3 res-10 tile set to the backend Python pipeline for the same file. The
Expo-era drift bomb (`mobile/src/lib/canonicalize.ts`, `preliminaryHash.ts`
having to agree with Rust forever) dies by construction: device hash and backend
hash come from the same compiled code.

## What was built (all inside `workout-parse/`, detector untouched)

| Piece | Where | Notes |
|---|---|---|
| Feature gate | `Cargo.toml`, `build.rs` | `default = ["python"]` keeps wheel/maturin behavior identical; `swift` adds UniFFI; `swift-cli` adds the bindgen binary only (clap never enters the iOS lib). PyO3/numpy are now optional deps. |
| PyO3 isolation | `src/lib.rs`, `src/polyline.rs` | Mechanical `#[cfg(feature = "python")]` on every pyclass/pyfunction/pymodule/use. Zero logic changes. |
| Shared metrics core | `src/lib.rs` → `compute_activity_metrics()` | The former `compute_metrics` pyfunction closure moved **verbatim** into a pure-Rust fn; the pyfunction and the Swift binding both delegate to it. One reward-bearing metrics path, now enforced at the language boundary too. |
| Swift surface | `src/swift_api.rs` | One record (`RideSummary`), one main fn (`parse_ride_summary`), two version probes. Zero new logic, zero new hashing — it calls `parse_file_bytes_for_version`, `hash_canonical_ride`, `compute_activity_metrics`, `project_to_h3`+`unique_cells`+`cells_to_strings`. |
| Bindgen CLI | `src/bin/uniffi_bindgen.rs` | Standard `uniffi::uniffi_bindgen_main()` shim, `required-features = ["swift-cli"]`. |
| Build script | `scripts/build_swift_bindings.sh` | Targets → bindgen → static libs → XCFramework → two harness binaries. All outputs under gitignored `target/swift/`. |
| Parity probes | `swift/harness/main.swift` + `scripts/parity_probe.py` | Print the identical 31-line key=value report through each binding; `diff` is the proof. |

UniFFI proc-macro mode (no UDL file) with `uniffi 0.29.5`. One placement gotcha:
`uniffi::setup_scaffolding!()` must sit at the **crate root** (`lib.rs`, cfg-gated),
not inside the `swift_api` module — the export macros resolve `crate::UniFfiTag`.

## Acceptance evidence

### 1. XCFramework builds (device + simulator slices)

`target/swift/WorkoutParseFFI.xcframework` with `ios-arm64` **and**
`ios-arm64-simulator` slices (device slice built fine; no `--skip-device`
needed). Static libs produced via `cargo rustc --crate-type staticlib` so the
committed `crate-type` stays `["cdylib", "rlib"]` and default builds are
untouched.

### 2. Sample ride parses on the iOS simulator

No app scaffold needed: the harness is a plain CLI compiled against the
`iphonesimulator` SDK and executed **inside a booted iPhone 17 simulator** via
`xcrun simctl spawn`. It parsed the real Philadelphia fixture
(`tests/validation/05_07_2015_Philadelphia_Pennsylvania.fit`, 7,369 samples,
2h38m ride) in well under a second. The macOS-fallback allowance was not used.

### 3. Parity: Swift (macOS) == Swift (iOS sim) == Python/PyO3, byte-identical

`diff` of the three reports (below binding= header): **zero differences**, on both
the FIT and the cross-format GPX fixture. Full report for the Philadelphia FIT —
every line identical across all three paths:

```
parser_version=5
canonical_hash_hex=873ab16ceb15a9e10713a3e9c4e10f626ab07016c551240ac359288a905b30af
canonical_hash_raw=873ab16ceb15a9e10713a3e9c4e10f626ab07016c551240ac359288a905b30af
sport=cycling
started_at_ms=1430994228000
total_elapsed_s=9514
sample_count=7369
duration_s=9514
moving_time_s=7651
distance_m=54703.9219
elevation_gain_m=633.971436
normalized_power_w=263
avg_power_w=178
max_power_w=949
power_sample_count=6907
power_sample_coverage_bps=9373
tss=366.150421
intensity_factor=1.31256831
kcals=1301
avg_hr_bpm=null
max_hr_bpm=null
heart_rate_sample_count=0
heart_rate_sample_coverage_bps=0
avg_speed_mps=7.45408535
max_speed_mps=21.0540009
avg_cadence_rpm=77
metrics_version=workout_parse_metrics_v1
tile_count_res10=495
tile_ids_sha256=fb5daa58181f6549c7a55d19d46e9125f9ebe8bdda502cda4decab9f08d3a50a
first_tile=8a2a13489a07fff
last_tile=8a2a13489aa7fff
```

Float honesty: every f32 is widened to double on both sides and printed `%.9g`
(9 significant digits round-trips f32 exactly), so equal strings mean
bit-identical f32 values, not lucky rounding. The tile line hashes the full
ordered tile list (SHA-256 of newline-joined ids) — 495 tiles compared, not
just the count. Second data point: `tests/fixtures/canonical_cross_format_ride.gpx`
(canonical hash `d6b8b8b2…981b`) — identical across all three paths as well.

The Python probe calls exactly what the backend adapter calls
(`parse_file_bytes` + `hash_canonical_ride` per
`compute_ride_identity_bytes_rust`, `compute_metrics(activity, ftp=200)` per
`calculate_metrics_rust`, `get_h3_strings(...)` at H3 res 10).

Reproduce: `bash workout-parse/scripts/build_swift_bindings.sh`, then run the
three probes on the same file and `diff`.

### 4. Python side unaffected

- `maturin develop --release` from this branch: builds and installs cleanly.
- Climb-regression hook (branch-built module vs frozen baseline, all 8
  validation FITs): **No regression detected.**
- Backend pytest, every test file importing `workout_parse` (12 files):
  **169 passed** (97 + 72). `tests/validation/test_canonical_v2_determinism.py`:
  **2 passed**.
- `cargo test`: 146 passed with default features **and** with
  `--no-default-features`.
- Default `cargo build`: same artifacts, same 23 pre-existing warnings, zero new.

## Numbers

| Metric | Value |
|---|---|
| Static lib, ios-sim / ios-device slice | 8.3 MB / 8.3 MB (pre-dead-strip archive; the fully linked harness binary is 2.2 MB total, which is the realistic app-size signal) |
| XCFramework on disk | 16 MB (both slices + headers) |
| Generated bindings | 1,159 lines Swift + 575 lines C header (fully generated, never hand-edited) |
| Full script run, warm cache | ~58 s wall (mostly xcodebuild + linking) |
| One-time extras, cold | uniffi-bindgen binary ~1 m 51 s; per-target lib compile ~30 s |
| Parse of the 2h38m Philadelphia FIT via Swift | ~30–50 ms |

## Binding ergonomics

Very good. Proc-macro UniFFI meant no UDL to maintain: `#[derive(uniffi::Record)]`
on one struct, `#[uniffi::export]` on three fns, done. Generated Swift is
idiomatic (`RideSummary` struct with camelCase fields, typed `throws` errors,
`Data`/optionals mapping cleanly). Cost signals for slice one: crossing the FFI
copies the record (fine for a per-ride summary; don't stream samples this way),
and Swift concurrency should treat `parseRideSummary` as blocking work for a
background executor.

## Gotchas recorded for slice one

1. `uniffi::setup_scaffolding!()` at crate root only (cfg-gated in `lib.rs`).
2. `cargo rustc --crate-type staticlib` avoids adding `staticlib` to the
   committed crate-type (which would slow every default build).
3. `build.rs` gates `pyo3_build_config` on `CARGO_FEATURE_PYTHON` — without
   this the iOS link pulls Python extension-module link args.
4. In-crate unit tests use `canonicalize`/`hash_canonical_ride_hex` directly,
   so that import stays unconditional with an `allow(unused_imports)` for
   binding-free builds.
5. The validation FIT fixtures (`tests/validation/*.fit`) are **gitignored** —
   they exist in the main checkout only. Fresh worktrees must point probes at
   the main checkout's copies (as the climb-regression hook already assumes).
6. `xcrun simctl spawn` runs plain CLI binaries inside a booted simulator and
   reads host paths — ideal for binding smoke tests without an app target.
7. The `swift`/`python` features are additive-safe but meant to be exclusive
   per artifact; nothing stops `--features python,swift` (it compiles), it's
   just not a shipping configuration.

## swift-bridge considered

Not chosen. swift-bridge generates leaner glue for Swift specifically, but:
UniFFI's proc-macro mode already hit near-zero boilerplate here; UniFFI is
maintained by Mozilla with a larger production footprint; and if the Kotlin
question ever reopens (Seeker/Android lapsed, not dead), the same annotations
emit Kotlin for free. Nothing observed in this spike argues for switching.

## Recommendation

**Adopt UniFFI as the slice-one parser lane.** Concretely, when the iOS lane
opens:

1. Slice one consumes `WorkoutParseFFI.xcframework` + generated Swift via a
   local SwiftPM target in the `ios/` app repo area (spike deliberately did not
   create it).
2. Wrap the build script into the app's build phase or a checked-in `make`
   target; keep bindings generation deterministic (`uniffi 0.29.5` pinned via
   `Cargo.lock`).
3. The parity probes should graduate into a CI truths-gate: same file, PyO3 vs
   Swift harness, `diff` must be empty (Gate-1-style clause for the mobile lane).
4. Surface growth (climb detection preview, polyline encode for upload, canon
   codec) follows the same pattern: extract-to-pure-core if any logic sits in a
   pyfunction body, then export — never reimplement. `compute_activity_metrics`
   is the template.
