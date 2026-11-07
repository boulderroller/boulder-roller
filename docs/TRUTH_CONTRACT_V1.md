# Truth Contract v1

**Status:** ACTIVE; V4-B canon amendment RATIFIED
**Effective:** 2026-02-27
**Latest amendment:** 2026-07-27 - Tim ratified the V4-B canon identity cutover contract and its controlled devnet activation. Co-KOM sporting recognition and deterministic legacy representative were separately ratified by Tim.
**Enforced by:** Pre-commit hooks, CI checks, runtime assertions
**Owner:** Core team

This document defines the non-negotiable invariants of the Boulder Rollers
climb detection and economic system. Any code change that violates these
invariants MUST be rejected. Any runtime state that violates them MUST
trigger fail-closed behavior (abstain), not a guess.

Changes to this contract require a signed change note with:
1. What invariant is changing and why
2. Benchmark diff showing the impact
3. Migration plan for all affected data

---

## 1. Determinism

**INV-DET-1:** Same input bytes + same detector version = identical output bits.

Specifically:
- The same FIT/GPX/TCX bytes, parsed with the same `workout-parse` version,
  MUST produce identical `ClimbV2` structs (same persistence pairs, same
  canonical bounds, same effort bounds, same signatures).
- Verified by pinned tests in `signature.rs` and `signature_v2.rs`.
- Violation is a P0 bug.

**INV-DET-2:** Signature generation is pure-functional.

Given identical elevation profiles, distances, and metadata, `generate_signature_v2()`
MUST return identical 64-byte signatures. No RNG, no timestamps, no ambient state.

**INV-DET-3:** Matching is symmetric.

`match_against(A, B)` MUST return the same result as `match_against(B, A)`.
DCT distance is symmetric by construction (L2 norm). Geometric pre-filter
uses relative difference, which is symmetric.

**INV-DET-4:** Different recordings of the same physical climb MAY produce
different detector outputs. This is expected (GPS jitter, device variance).
Detector DCT matching (`DCT_MATCH_COEFFS=6`) may bridge that gap for discovery,
replay, and canon nomination. It is not V4-B Climb or Vault identity and cannot
authorize economics.

---

## 2. Boundary Invariants

**INV-BND-1:** The legacy detector's persistence boundaries (`birth_idx`,
`death_idx`) and trimmed display boundaries (`effort_start_idx`,
`effort_end_idx`) are separate detector domains. They MUST NEVER be mixed, and
neither domain is the V4-B economic traversal boundary.

| Domain | Used for | Source |
|--------|----------|--------|
| Detector canonical (birth/death) | Detector signature generation, discovery clustering, replay, canon nomination | Persistence homology |
| Detector display (effort start/end) | Non-authoritative detector display metrics and localized discovery endpoints | Gradient-walk trim within detector canonical bounds |
| D11 traversal (start/finish gate crossings) | Accepted canon effort interval, Record Board time, exact Vault-binding eligibility | Interpolated crossings of the ratified registry gates |

**INV-BND-2:** Detector signatures MUST be computed from detector canonical
bounds, not detector display/effort bounds.

Detector canonical bounds are topologically stable. Detector display bounds
vary with gradient trimming parameters. Discovery signatures MUST survive
parameter tuning.

Localized detector endpoints MAY corroborate the detector signature for
discovery, but they are not signature inputs. Detector signatures, endpoints,
and any reconciliation of them remain discovery/replay evidence only; changing
them cannot authorize or reinterpret a completion.

**INV-BND-3:** Detector display/effort bounds MUST be contained within detector
canonical bounds.

```
birth_idx <= effort_start_idx <= effort_end_idx <= death_idx
(or reversed for descending-first segments)
```

**INV-BND-4:** Detector effort trimming MUST NOT exceed
`EFFORT_TRIM_MAX_RATIO` (0.4) from each end of the detector canonical range. If
trimming would exceed this, original detector canonical bounds are used for the
detector display interval. This remains a discovery/display invariant only.

---

## 3. Detector Matching Invariants (Discovery and Replay Only)

Every invariant in this section governs the frozen detector matcher used for
discovery, diagnostics, replay, and canon nomination. No result from this
pipeline identifies a V4-B Climb or Vault, clears abstention, or authorizes a
completion, tribute, Record Board write, or settlement input.

**INV-MAT-1:** When the detector matcher is run, its multi-gate discovery
pipeline is applied in strict order. No discovery gate may be skipped.

```
Gate 0: Version      — reject Incompatible if version mismatch
Gate 1: H3 proximity — reject NoMatch if grid_distance > 3
Gate 2: Geometric    — reject NoMatch if vert or distance differ > 25%
Gate 3: DCT shape    — d_rel < 0.08 = Match, < 0.15 = ProbableMatch, else NoMatch
```

**INV-MAT-2:** Only DCT coefficients 0 through `DCT_MATCH_COEFFS - 1` (currently 0-5)
are used for matching. Higher coefficients carry GPS jitter, not climb shape.

**INV-MAT-3:** Same-climb detector pairs (same physical climb, different
recordings) MUST produce `d_rel < 0.015` for definite discovery matches. This
is validated against the corpus of 27 known duplicate ride pairs and has no
economic-authority meaning.

**INV-MAT-4:** Detector GPS discovery matching applies oriented 150m
start-to-start and end-to-end proximity checks around the detector signature
verdict. If either endpoint pair is farther apart, the discovery candidate is
rejected. A passing endpoint check is still discovery only and never
reward-grade evidence.

**INV-MAT-5:** GPS validity requires finite latitude in `[-90, 90]` and
longitude in `[-180, 180]`. Exact `(0, 0)` is treated as a device no-fix
sentinel. A legitimate point on latitude zero or longitude zero is valid.

---

## 4. Identity Commitment and Discovery Signature Invariants

**INV-SIG-1:** Every V4-B Vault identity is exactly one 64-byte D12 canon
commitment (128 hex characters). Any other length is rejected before a
transaction is built, indexed, or used for economics.

**INV-SIG-2:** A D12 commitment begins with `0x01`, carries one non-zero
`canon_id` UUID and one non-zero big-endian `u16` version, reserves bytes
19-31 as zero, and ends with the exact 32-byte canonical profile hash.

**INV-SIG-3:** The backend, indexer, and Anchor program share frozen codec
vectors. A wrong prefix, zero or overflowing version, non-zero reserved byte,
malformed UUID, or mismatched profile hash is corrupt and fails closed.

**INV-SIG-4:** Detector signatures no longer identify Vaults and cannot
authorize a completion, tribute, Record Board write, or settlement input.
They remain deterministic discovery evidence only. The detector parameter
drift guard remains; the old Vault signature-stability blocker retired at the
V4-B cutover because preserving detector bytes is no longer an economic
identity invariant.

**INV-SIG-5:** The legacy detector-v2 layout remains frozen for replay and
discovery compatibility, not Vault authority:

| Offset | Size | Field | Unit |
|--------|------|-------|------|
| 0 | 1 | version | 0x02 |
| 1 | 1 | flags | terrain(2b), direction(1b), has_power(1b) |
| 2-3 | 2 | vert | meters, u16 BE |
| 4-5 | 2 | distance | decameters, u16 BE |
| 6-7 | 2 | avg_gradient | percent * 100, i16 BE |
| 8-15 | 8 | h3_anchor | H3 resolution 10 cell, u64 BE |
| 16-47 | 32 | dct_coeffs | f16[16], DCT-II of gradient profile |
| 48-63 | 16 | checksum | BLAKE3(bytes[0..48])[0..16] |

**INV-SIG-6:** The V4-B D12 canon commitment layout is frozen:

| Offset | Size | Field | Rule |
|--------|------|-------|------|
| 0 | 1 | commitment version | `0x01` |
| 1-16 | 16 | `canon_id` | UUID bytes |
| 17-18 | 2 | canon revision | non-zero `u16` big-endian |
| 19-31 | 13 | reserved | all zero |
| 32-63 | 32 | canonical profile hash | exact BLAKE3 profile digest |

**INV-SIG-7:** Ratified registry measurements remain precise database truth.
`canon_climbs.length_m`, `vert_m`, and `avg_gradient_pct` are never overwritten
with values chosen to fit an account field. The sole registry-to-chain scalar
projection is `boulderroller_chain_metric_projection_v1`. For a nonnegative
decimal `x`, it computes `floor(x * scale + 0.5)` using decimal arithmetic, with
scales `1` for whole-meter length, `10` for vertical decimeters, and `100` for
gradient basis points. The projected length and vertical gain must fit a
positive `u32`; projected gradient must fit `u16`, and its raw value must remain
nonnegative. Binary floating-point rounding is not an authority boundary.

**INV-SIG-8:** V4-B Climb and Vault scalar metric fields are immutable chain
projections, not replacements for registry measurement truth. D12 identity
contains only its layout byte, `canon_id`, revision, reserved bytes, and the
canonical-profile hash. Length, vertical gain, gradient, display name, and
their projections do not enter the D12 bytes, commitment SHA-256, Climb PDA, or
version-index PDA. The registrar recomputes the named projection from the raw
artifact row; the indexer recomputes it from PostgreSQL `numeric` values and
requires exact equality with the decoded chain integers.

**INV-SIG-9:** Every V4-B instruction that can consume the global
`VaultCounter` is reservation-authorized before it mutates that counter. The
wallet-funded DUNG and CAL+USDC constructors require a signing
`sponsor_authority` equal to `ProgramConfig.backend_authority`; the backend adds
that signature only to the exact transaction bytes held by one live canonical
prepare/submit reservation. Direct/admin and Balance-funded constructors are
unavailable in V4-B until they participate in the same reservation contract.
A rider signature, registered Climb, or valid payment alone cannot consume a
Vault ID.

---

## 5. Unit Invariants

**INV-UNIT-1:** All elevations are in meters (f64 for computation, f32 for
storage from FIT files). Never feet, never centimeters.

**INV-UNIT-2:** All distances are in meters (f64). The sole exception is the
v2 signature `distance` field which stores decameters (u16) for range.

**INV-UNIT-3:** All gradients are in percent (f64). `5.0` means 5%.

**INV-UNIT-4:** All times are in seconds. `TileSample.t` is seconds from
activity start (i64). `ClimbV2.time_s` is duration (u32).

**INV-UNIT-5:** All GPS coordinates are WGS84 degrees (f64). The sole
internal exception is `ParsedActivity.lat_e7` (degrees * 1e7, i32) which
is converted to f64 degrees before any computation.

**INV-UNIT-6:** H3 resolution is always 10. This is enforced by the
`h3-resolution-guard` pre-commit hook. Changing this corrupts all tile data.

---

## 6. Economic Invariants

**INV-ECON-1:** A Vault completion requires one accepted D11 canon traversal
whose exact registry row, `canon_id`, revision, canonical profile hash, D12
commitment, indexed Climb, attached Vault, and finalized generation-2
constructor activation all agree. Detector signatures, similarity, endpoints,
cached Vault IDs, and geographic heuristics are discovery evidence only and
cannot trigger a completion.

**INV-ECON-2:** The ratified forward-only tribute policy is
`cal_tribute_segment_tss_v2`. The rider receives the full attested CAL; tribute
is a separate flow-meter amount computed from each eligible Climb's own TSS:
```
segment_tss_base_units_i = floor(
  segment_np_duration_s_i * segment_np_milliwatts_i^2 * 100 * 1_000_000_000
  / (reward_ftp_w^2 * 1_000_000 * 3_600)
)
exact_tribute_budget_base_units = sum(segment_tss_base_units_i)
```
Segment NP comes from the authoritative pause-aware Climb window, frozen as
integer milliwatts with its NP duration. Each amount is floored independently
to one CAL base unit. Missing, insufficient, or zero power has zero tribute
with no gradient proxy. The immutable ride-time reward FTP supplies the
denominator; mutable profile FTP cannot change allocation. One fastest
qualifying traversal per ride and Vault supplies the single receipt.
Overlapping eligible climb windows require review, and the sum never exceeds
full attested CAL. No floating-point accumulation or per-climb vertical proxy
may reinterpret the frozen plan; historical plans retain their original
policy.

**INV-ECON-3:** Detector uncertainty, similarity, endpoint proximity, and
confidence tiers may rank discovery evidence, but the resulting detector climb
always abstains from economics with `MATCH:canon_traversal_required`. Only a
fresh accepted D11 traversal may proceed to the exact finalized binding gate.
See Abstention Policy (Section 7).

**INV-ECON-4:** Record Board and Leaderboard rankings use the accepted D11 canon
traversal's frozen whole-second `time_s`: the duration between its interpolated
exact start-gate and finish-gate crossings. Legacy detector EFFORT/display
bounds, gradient-walk trims, signatures, and endpoints cannot set or reinterpret
that time.

**INV-ECON-5:** The fastest validated time changes only on strict less-than:
`new_time < current_kom_time`. A strictly faster whole-second time replaces the
full prior KOM/co-KOM set. An equal fastest time does not change
`current_kom_time`; when that rider is seated inside the ten-entry Leaderboard,
the rider joins the co-KOM set.

**INV-ECON-6:** Every seated rider tied at the fastest validated whole-second
time is a co-KOM. All receive crown recognition and `T-1` on detailed rider
surfaces. This recognition MUST NOT change standard competition ranks, the
ten-seat cutoff, pooled occupied-position percentages, exact payout base-unit
bytes, or `client.v1` occupied-row `rank`.

The singular ABI-compatible `Vault.kom_holder` is only a deterministic legacy
representative of that set, selected by earliest original ride `completed_at`
and then wallet bytes. It MUST NOT receive an extra payout or sole-winner
sporting meaning. Metadata stewardship remains a separate Local Legend role.
The deployed V4-A metadata path's post-Founder coupling to `kom_holder` is
transitional compatibility behavior; this invariant neither broadens that
authority nor changes the ABI. A separately ratified metadata-authority/ABI
rollout MUST land before an equal-fastest completion may rotate `kom_holder`;
otherwise deterministic representative selection would silently transfer live
metadata authority.

---

## 7. Abstention Policy

Abstention means: the climb is detected and stored for display purposes,
but it does NOT trigger vault completion, CAL tribute, or leaderboard entry.

**INV-ABST-1:** A climb MUST abstain from economic actions when ANY of:
- no accepted D11 canon traversal exists for that ride window
- the exact registry identity or D12 commitment is missing or mismatched
- the Climb/Vault binding or generation-2 constructor activation is not exact
  and finalized
- ride or Climb sensor integrity is below the ratified threshold

Detector confidence, similarity, endpoints, and signatures may still be stored
as discovery evidence, but they cannot satisfy any item above.

**INV-ABST-2:** Abstention is stored as `economic_eligible = false` on
the climb pattern record. The climb is still visible to the rider.

**INV-ABST-3:** A detector discovery row cannot be promoted directly to
economic-eligible by backfill. Promotion means compiling and ratifying an
explicit canon revision; economics still require a fresh accepted D11
traversal and one exact finalized Climb/Vault/Activation binding. Terrain
priors or retroactive GPS matches may strengthen a nomination, not authorize a
completion.

---

## 8. Data Quality Guards

**INV-DATA-1:** GPS sentinel values MUST be rejected:
- FIT: `INT32_MIN / 1e7 = -214.748...` degrees
- Null Island: `(0.0, 0.0)`
- Out of range: `|lat| > 90` or `|lon| > 180`

Enforced by `is_valid_gps()` in `workout-parse/src/climb/utils.rs`.

**INV-DATA-2:** Per-step distance MUST be capped at 500m. Both haversine
and time-fallback paths enforce this independently.

**INV-DATA-3:** VAM MUST be capped at 2500 m/hr. Climbs exceeding this
are rejected as sensor artifacts.

**INV-DATA-4:** Minimum vertical gain is 5.0m (persistence detector).
Below this threshold, most "climbs" are barometric noise or overpasses.

**INV-DATA-5:** Gradient profiles are clamped to [-10%, +20%] for
signature encoding. Values outside this range are truncated, not rejected.

**INV-DATA-6:** Maximum activity duration is 48 hours (172,800 seconds).
Activities exceeding this are rejected as corrupt timestamps.

**INV-DATA-7:** Every activity MUST have a `SensorIntegrityReport` computed
before economic decisions. The report scores GPS validity/continuity,
elevation plausibility, sampling regularity, and produces a composite
integrity score (0.0-1.0). Activities with integrity < 0.40 MUST abstain
from all economic actions. Enforced by `compute_sensor_integrity()` in
`backend/app/services/sensor_integrity.py`.

**INV-DATA-8:** GPS teleportation (>500m between consecutive samples) MUST
be detected and counted. More than 3 teleportation events in a single
activity triggers abstention. Enforced by the sensor integrity layer.

**INV-DATA-9:** Barometric elevation values outside [-500m, +5500m] MUST
flag the activity as `elev_plausible = false`. Climbs from implausible-
elevation activities MUST abstain from economic actions.

---

## 9. Version Control

**INV-VER-1:** The detector version (persistence vs momentum) MUST be
recorded with every climb pattern for audit trail.

**INV-VER-2:** Signature version (v1 vs v2) is embedded in the signature
itself (byte 0 for v2, implicit for v1). Both versions can coexist.

**INV-VER-3:** When the detection algorithm changes, both old and new
results MUST be compared against the benchmark corpus. Changes that
degrade benchmark metrics MUST NOT ship without signed justification.

---

## Enforcement

| Invariant class | Enforcement mechanism | Severity |
|----------------|----------------------|----------|
| Detector signature replay stability | Pinned cross-platform tests (non-economic) | P1 |
| H3 resolution | Pre-commit hook (blocks) | P0 |
| Determinism | Pinned tests in Rust | P0 |
| Checksum validity | Runtime assertion | P0 |
| GPS rejection | Runtime validation | P1 |
| Boundary separation | Code review, type system | P1 |
| D11 traversal and exact finalized binding | Runtime checks and frozen evidence | P0 |
| Unit conventions | Code review, naming | P2 |
| Abstention policy | Runtime checks | P1 |
| Benchmark regression | CI check (to implement) | P1 |

---

## Change Log

| Date | Change | Justification |
|------|--------|---------------|
| 2026-07-27 | RATIFIED: INV-BND, INV-MAT, INV-ECON-1/2/3/4, and INV-ABST-1/3 aligned to V4-B canon authority | Tim approved the amendment and controlled devnet cutover. D11 gate crossings and D12 exact binding replace detector boundaries, similarity, and endpoints as completion and Record Board authority; tribute follows the ratified ride-level segment-NP fixed-budget policy. Signed change note: [`history/V4_B_TRUTH_CONTRACT_CHANGE_2026-07-21.md`](../history/V4_B_TRUTH_CONTRACT_CHANGE_2026-07-21.md). |
| 2026-07-21 | INV-ECON-5 amended and INV-ECON-6 added | Tim ratified true co-KOM recognition while preserving rtie rank, cutoff, payout, and ABI behavior; signed change note: [`history/CO_KOM_TRUTH_CONTRACT_CHANGE_2026-07-21.md`](../history/CO_KOM_TRUTH_CONTRACT_CHANGE_2026-07-21.md) |
| 2026-02-27 | v1 drafted | Initial contract from invariant audit |
