# workout-parse Teardown — Staff Systems Review (2026-08-07)

Scope: design-sanity review of the Rust parsing/metrics/signature crate from the
"staff systems engineer, sensor data pipelines" perspective. Not a pen test, not
a fuzzing campaign, not a DSP critique of the frozen detector. Question asked:
*is what we're doing really smart, given this becomes public-good on-chain
infrastructure?*

**Verdict: yes.** The crate is engineered above startup grade in exactly the
places that matter for an attestation economy. One low-severity crafted-file
crash path found, plus a short list of hardening nits. No architectural
mistakes.

---

## What is genuinely smart (keep doing this)

1. **Versioned parser semantics (V1–V5) that preserve historical bugs.**
   `parse_bytes_for_version` deliberately replays V1's wrong
   missing-elevation-as-sea-level interpretation and V1's file-type detection
   quirks so old attestations stay reproducible. This is attestation-system
   thinking most teams only learn after their first hash break.
   ([lib.rs:158](../../workout-parse/src/lib.rs), `canonicalize.rs`)

2. **Integer-only canonical ride form.** Canonicalization buckets to 1 Hz,
   scales everything to integers (e6 coords, dm elevation, cms speed) before
   JSON + SHA256. No float-formatting nondeterminism in the replay hash. Golden
   byte-for-byte and hash test vectors pinned in tests.

3. **Money-math hygiene in metrics.** NP is computed per-segment with a 30 s
   pause threshold so pauses can't inflate it; TSS uses NP-eligible duration
   (`normalized_power_duration_s`), not elapsed time; ride-level and
   climb-window power metrics share one function (`compute_power_metrics`) so
   they cannot drift; 0 W-coasting vs sensor-dropout vs missing are distinct
   states with documented sentinels; sample-coverage basis points feed the
   evidence tiers.

4. **FTP is not a rider-controlled lever.** The biggest TSS-inflation attack
   (understate FTP) is closed in `backend/app/services/reward_ftp.py`: bounded
   50–500 W, network default 200 W, only operator/trusted-provider/verified-test
   sources can override, provenance frozen per ride, policy-versioned. The
   crate computes; the policy layer decides what counts.

5. **Adversarial-input basics are done.** Zip-bomb limits (100 MB, 100×
   ratio, 10 entries, recursion depth 2), 48 h duration cap with
   overflow-checked timestamp math, monotonicity validation, content-based file
   sniffing rather than trusting extensions.

6. **Signature v2 fails closed.** BLAKE3 checksum on decode, version gate, H3
   proximity gate that returns NoMatch on any H3 error, geometric pre-filter,
   then DCT distance. Deterministic pinned-hex test with an explicit "do not
   change without vault migration" warning. Explicit canonical f16 zero-sign
   table so cross-platform libm residuals can't fork the wire bytes —
   someone got burned once and fixed it properly.

7. **FFI boundary invariants hold.** `ParsedActivity` has no Python
   constructor, so every instance downstream of the boundary passed timestamp
   validation. GIL is released around all heavy work. Errors map to typed
   Python exceptions, not panics, on all parse paths.

8. **Defense-in-depth layering is coherent.** The parser doesn't check
   timestamp plausibility (1970 / future rides) — but the effort policy does
   (economy start, 10 min clock skew, 30-day staleness, 36 h duration), and it
   also gates GPS-only rides out of automatic CAL. Right check, right layer.

## Findings

### F1 — NaN distance panics `compute_metrics` (LOW, fix cheap)
[lib.rs:2564](../../workout-parse/src/lib.rs): `dist.iter().max_by(|a, b|
a.partial_cmp(b).unwrap())`. A FIT file can encode NaN in the distance field
(`Value::Float64`); parse succeeds, then metrics computation panics. PyO3
converts it to `PanicException` so the worker survives, but it's an ungraceful,
crafted-file-triggerable failure on the hot path. Fix: `total_cmp`, or filter
non-finite distances at parse/metrics entry.

### F2 — `has_elevation()` accepts NaN (hardening nit)
`climb/types.rs:26` checks `is_some()`, not `is_finite()`. Safe today only
because the backend adapter (`workout_parse_adapter.py`,
`_finite_float_or_none`) filters NaN before building tile samples — the
invariant lives one layer above the API that depends on it. If the crate goes
public, a direct caller feeding V2+ parser output (missing elevation = NaN)
into `detect_climbs*` gets NaN-poisoned detection. Fix:
`self.elevation_m.map_or(false, f64::is_finite)`.

### F3 — No lat/lon range validation in GPX/TCX parse (nit)
`(v * 1e7) as i32` saturates (defined behavior, no UB), and downstream layers
(H3 `LatLng::new`, haversine fallback range checks) filter garbage coordinates,
but the parser itself accepts lat 95° etc. Cosmetic for now; worth a range
clamp if the crate is published as a general-purpose parser.

### F4 — FFI sample conversion silently drops malformed dicts (design note)
The `detect_climbs*` entry points `filter_map` away any tile-sample dict
missing `t` or with wrong types. Silent data loss instead of an error. Fine as
an internal contract with our own backend; a public API should count and report
dropped samples.

### F5 — `dict.set_item(...).unwrap()` in PyO3 result building (cosmetic)
Effectively infallible (fresh dicts), but `?` is free and the crate is
otherwise disciplined about this.

## Non-findings (checked, fine)

- **Smart-recording carry-forward can't meaningfully inflate power**: hold-last
  is bounded by the 30 s pause threshold, and power values are
  attacker-authored anyway — forgery is the effort-integrity thread's problem
  (physics residuals), not the parser's.
- **Zip handling** extracts one best-candidate entry with size/ratio caps.
- **Speed metrics** sanity-clamp 0–100 m/s; GPS-distance fallback validates
  coordinate ranges and caps per-step haversine at 500 m.
- **Panic sweep** of runtime paths: the remaining `unwrap()`s are guarded by
  upstream filters (elevation filters before elevation unwraps, first/last
  after emptiness checks). `canon/mod.rs` has a high unwrap count but is the
  offline compiler lane, not the rider-facing hot path.

## Recommendation

Fix F1+F2 as one small bead (two one-line changes plus tests). F3–F5 only
matter at open-sourcing time — fold them into whatever "publish the crate"
checklist exists then, alongside the fuzzing pass that was already discussed
and deferred. Nothing here blocks cohort work.
