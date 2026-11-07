# Ride Canonicalization Spec

**Status:** READY FOR IMPLEMENTATION  
**Date:** 2026-04-15  
**Authority:** Narrow deterministic spec under [PROTOCOL_TRUTHS](/Users/gabetemp/curahee/BoulderRoller-v2/docs/PROTOCOL_TRUTHS.md:1) and [PROTOCOL_ALIGNMENT_FIX_PLAN](/Users/gabetemp/curahee/BoulderRoller-v2/docs/design/PROTOCOL_ALIGNMENT_FIX_PLAN.md:777)

---

## Purpose

This document defines the deterministic `ride_hash` derivation used by Boulder
Roller for:

- structural replay protection
- attestation identity
- cross-language verification
- chain-visible economic auditability

This spec is intentionally narrow. It exists because ride canonicalization is
cross-language, test-vector driven, and expensive to change later.

If this document conflicts with broader protocol semantics, semantics live in
`PROTOCOL_TRUTHS.md` and this document must be updated to match.

---

## Goals

Version 1 canonicalization must provide:

- deterministic `ride_hash` derivation from parsed ride data
- stable behavior across Rust, Python, and future indexer/client tooling
- exact replay protection for the same parsed ride content
- clear exclusion of non-economic metadata
- test-vector compatibility in CI

Version 1 does **not** try to be a fuzzy deduplication oracle for every possible
lossy export of the same physical ride.

---

## Non-Goals

Version 1 canonicalization does **not** guarantee:

- equivalence across materially different third-party exports of the same ride
- normalization of privacy-redacted and full-fidelity traces to the same hash
- deduplication across distinct recording devices with different sample streams
- proof that a ride physically happened

Version 1 is an identity and replay-protection primitive, not a fraud-proofing
system by itself.

---

## Normative Output

For `parser_version = 1`, canonicalization produces:

1. a canonical UTF-8 byte sequence
2. `ride_hash = SHA256(canonical_bytes)`
3. a lowercase hex string representation of the digest for external display

The digest bytes are the canonical identity. The hex string is a transport
representation only.

---

## Parser Semantic Version Gate

Parser semantics are an immutable replay contract, not a package release
label. A change that can alter accepted FIT, GPX, or TCX bytes, canonical
bytes, or economically authoritative parser output MUST add `PARSER_VERSION_Vn`
in both Rust and TypeScript, set
`CURRENT_PARSER_VERSION` to that explicit constant, add a new
`canonical_ride_vn_vectors.json` golden vector, and add raw-byte regression
coverage where source parsing changed. Existing `PARSER_VERSION_Vn` constants,
dispatch arms, vectors, and hashes MUST remain unchanged.

CI runs `tools/check_parser_semantics_version.sh` against the branch base. It
fails when `workout-parse/src/lib.rs`, `workout-parse/src/canonicalize.rs`, or
`mobile/src/lib/canonicalize.ts` changes without both language constants and a
versioned golden vector. An unchanged-version exemption requires a commit
between base and HEAD with this trailer and a one-line indented reason:

```text
Parser-Semantics: unchanged
  Register a Python binding and retain device-only evidence; canonical outputs are unchanged.
```

The guard must also reproduce the current-version and cross-format vectors
from HEAD: a fresh `workout_parse` build for Rust edits, the mobile canonicalizer
tests for TypeScript edits, or both. Existing golden vectors and their source
inputs cannot change under the exemption. Missing tools, failed verification,
or a missing declaration retain the version-bump requirement. Review cannot
waive a bump for output-affecting behavior.

### V1 through V5

- **V1** replays raw source bytes with the historical pre-`9e6d49aa` parser:
  old auto-detection prefix order, raw XML qualified-name handling, legacy XML
  element-state/self-closing behavior, and missing GPX/TCX elevation as `0.0`.
  It is selected explicitly from recorded provenance and is never reconstructed
  by serializing a V2 parse with `parser_version: 1`.
- **V2** was introduced by
  `9e6d49aa217c522222bb9922282df40ea799afeb`. It uses local XML names, resets
  XML state correctly, preserves missing elevation as missing, and validates a
  bounded ordered timeline. The V2 source provenance is tied to that commit;
  the V1 provenance source is `e212e9e57ef93635b7ca5d21a68a5834af3ec1d0`.
- **V3** retains V2 source and canonical-field rules while binding the
  authoritative metrics engine introduced by
  `5d4c2c2eb150115a9b2deb771e7bcde2e199f3c7`.
- **V4** retains V3 source, canonical-field, and metrics rules while binding
  the authoritative canonical-v2 geographic climb output introduced by
  `aa77d5b7962252c396b0ef1f95aef1cb4d048edf`.
- **V5** is current. It retains every V4 source, canonical-field, metrics, and
  geographic matching rule while binding the authoritative climb-window power
  metrics introduced by `73bfee87359b0573014c16674e36ae6639a0276f`.

Input-size, decompression, and ordered-timestamp bounds are universal safety
checks. They may reject malformed or unreasonably large historical input, but
they do not reinterpret canonical fields from a valid V1 ride.

Raw FIT/GPX/TCX replay is authoritative in Rust/backend Python. Mobile uses the
same versioned canonical activity algorithm and V2-through-V5 timestamp bounds
before upload; it does not claim to parse arbitrary raw FIT/GPX/TCX bytes locally.
Cross-format vectors intentionally retain format-limited streams (for example,
FIT speed and TCX distance) instead of pretending those exports have identical
canonical JSON.

---

## Input Model

Canonicalization operates on the normalized parsed activity surface produced by
`workout-parse`, not directly on raw FIT/GPX/TCX bytes.

The relevant input fields are the `ParsedActivity` shape exposed in
[workout-parse/src/lib.rs](/Users/gabetemp/curahee/BoulderRoller-v2/workout-parse/src/lib.rs:31):

- `time_ms`
- `lat_e7`
- `lon_e7`
- `elevation_m`
- `pwr_w`
- `hr_bpm`
- `cadence_rpm`
- `speed_mps`
- `dist_m`
- `sport`
- `started_at_ms`

All other parser outputs are explicitly excluded unless this spec says
otherwise.

---

## Canonicalization Contract

### 1. File-Type Independence Boundary

Version 1 canonicalization is designed to normalize rides across supported file
types **only when they preserve equivalent second-level activity data after
parsing**.

That means:

- the same FIT file uploaded twice must always hash identically
- the same parsed activity delivered through different app paths must hash
  identically
- a GPX/TCX export that materially drops power, cadence, timestamps, or route
  precision may hash differently from the original FIT

This is acceptable in V1. Economic replay protection is the primary target.

### 2. Economic Time Basis

The economically authoritative ride clock is the parsed ride time, not upload
time.

- `started_at_ms` anchors the canonical timeline
- `completed_at_ms` is derived from the final canonical sample second
- all per-sample time is represented as `sec_offset` from ride start

Absolute upload/ingestion times are never included in canonicalization.

### 3. Sample Timeline

Version 1 canonicalization collapses the parsed activity into **1 Hz second
buckets**.

For each raw sample timestamp `t_ms`:

`sec_offset = floor((t_ms - started_at_ms) / 1000)`

All raw samples with the same `sec_offset` belong to the same canonical bucket.

The canonical ride includes one bucket for every `sec_offset` in the closed
range:

`0 .. last_sec_offset`

where `last_sec_offset` is derived from the final raw sample in `time_ms`.

If no raw sample lands in a second bucket, that bucket still exists in the
canonical output with all sensor fields `null`.

This preserves duration and prevents sampling-rate-dependent omission of empty
seconds.

### 4. Per-Bucket Aggregation

If multiple raw samples land in the same second bucket:

- `lat_e6`, `lon_e6`, `elev_dm`, `dist_dm` use the **last non-missing** value in
  the bucket
- `speed_cms`, `power_w`, `hr_bpm`, `cadence_rpm` use the **rounded arithmetic
  mean** of all non-missing values in the bucket

Rounding rules:

- round half away from zero
- all stored canonical values are integers

If a field has no non-missing values in the bucket, it is `null`.

No interpolation or forward-fill occurs in V1.

### 5. Quantization Rules

All canonical numeric fields are reduced to explicit integer units before
serialization:

- `lat_e6`: latitude in degrees multiplied by `1_000_000`, rounded to nearest
  integer
- `lon_e6`: longitude in degrees multiplied by `1_000_000`, rounded to nearest
  integer
- `elev_dm`: elevation in meters multiplied by `10`, rounded to nearest integer
- `dist_dm`: cumulative distance in meters multiplied by `10`, rounded to
  nearest integer
- `speed_cms`: speed in meters per second multiplied by `100`, rounded to
  nearest integer
- `power_w`: integer watts
- `hr_bpm`: integer beats per minute
- `cadence_rpm`: integer revolutions per minute

Location is reduced from parser `e7` precision to `e6` intentionally. This keeps
the canonical surface stable and easier to reproduce cross-language.

### 6. Sport Normalization

`sport` is included in canonicalization as:

- lowercase ASCII
- trimmed
- empty string if unavailable

No device-specific or vendor-specific sport metadata is retained.

---

## Included Fields

The canonical JSON object for V1 must contain exactly these top-level fields, in
sorted-key order during serialization:

- `parser_version`
- `samples`
- `sport`
- `started_at_ms`

Each sample object must contain exactly these keys, also in sorted-key order:

- `cadence_rpm`
- `dist_dm`
- `elev_dm`
- `hr_bpm`
- `lat_e6`
- `lon_e6`
- `power_w`
- `sec_offset`
- `speed_cms`

All keys must always be present. Missing values are encoded as `null`, never
omitted.

---

## Excluded Fields

The following fields must not affect `ride_hash` in V1:

- device name
- device serial
- file name
- file size
- raw file bytes
- upload time
- request metadata
- comments, descriptions, titles
- user-entered labels
- calories
- TSS
- normalized power
- climb matches
- terrain class
- weather
- attribution or source account IDs

These may be useful elsewhere in the product, but they are not part of ride
identity.

---

## Canonical Serialization

The canonical byte representation is minified UTF-8 JSON with:

- no insignificant whitespace
- object keys sorted lexicographically
- arrays preserved in their defined order
- integers rendered in base-10 without leading zeroes
- `null` for absent values

Example shape:

```json
{
  "parser_version":1,
  "samples":[
    {
      "cadence_rpm":85,
      "dist_dm":0,
      "elev_dm":1234,
      "hr_bpm":null,
      "lat_e6":39912345,
      "lon_e6":-105123456,
      "power_w":210,
      "sec_offset":0,
      "speed_cms":623
    }
  ],
  "sport":"cycling",
  "started_at_ms":1713120000000
}
```

Implementations must not rely on language-default JSON key ordering.

---

## Hash Function

Version 1 uses:

- hash algorithm: `SHA-256`
- digest input: canonical UTF-8 JSON bytes
- digest output: 32 bytes

Display form:

- lowercase hex string
- exactly 64 hex characters

Any future digest algorithm change requires a new `parser_version`.

---

## Parser Version Policy

`parser_version` is part of the canonical object and therefore part of the
hash. It also selects the immutable pipeline provenance for ride economics.

Increment `parser_version` when canonicalization or economically authoritative
parser output changes, such as:

- raw FIT/GPX/TCX interpretation that changes a normalized canonical field
- bucket aggregation rules
- unit quantization
- included/excluded fields
- serialization rules
- hashing algorithm
- the authoritative metrics engine
- reward-bearing climb detection or matching output

Do **not** increment `parser_version` for:

- non-canonical parser performance changes
- non-economic discovery or detector changes
- UI changes
- indexer changes

Version 1 must remain reproducible forever once shipped.

---

## Compatibility and Migration

When a future version is introduced:

- old `ride_hash` values remain valid
- old attestations remain queryable by `(parser_version, ride_hash)`
- new rides use the latest supported `parser_version`
- the chain/backend must never reinterpret an old attestation under a new
  parser version

If a future migration wants to compare rides across versions, it must do so
explicitly at the application layer. Cross-version identity is not implicit.

---

## Reference Algorithm

V1 canonicalization must behave as if it executes the following algorithm:

1. Parse raw ride file into `ParsedActivity`.
2. Read `started_at_ms` and `time_ms`.
3. For each raw sample index `i`, assign it to a `sec_offset`.
4. Build a bucket for every second from `0` to `last_sec_offset`.
5. Aggregate bucket fields using the V1 rules above.
6. Quantize all numeric values to canonical integer units.
7. Build the canonical JSON object with exact required keys.
8. Serialize to minified sorted-key UTF-8 JSON.
9. Compute `SHA-256` over the bytes.

Any implementation that produces different bytes for the same parsed activity is
wrong.

---

## Test Vectors

V1 cannot be considered implemented until test vectors exist.

Each test vector must include:

- fixture file name
- raw fixture SHA-256
- file type
- expected `parser_version`
- expected canonical JSON SHA-256
- expected `ride_hash`
- expected first three sample buckets
- expected final sample bucket

Required vector coverage:

- FIT with full GPS + power + HR + cadence
- FIT with GPS but no power
- GPX with sparse timestamps
- TCX with missing cadence/HR
- ride with repeated timestamps inside one second
- ride with missing whole-second buckets
- ride with no GPS but valid timing/power

Vectors must live in-repo and run in CI for both Rust and Python surfaces.

---

## Security and Audit Notes

This spec prevents accidental or adversarial replay of the same parsed ride
through multiple ingestion paths. It does not prove the ride is genuine.

Fraud resistance still depends on:

- backend attestation policy
- climb matching correctness
- anomaly detection
- optional future attester decentralization

Canonicalization is one layer in the trust boundary, not the whole boundary.

---

## Implementation Obligations

The minimum implementation work implied by this spec is:

- add `canonicalize(activity: &ParsedActivity, parser_version: u32) -> Vec<u8>`
  to `workout-parse`
- add `hash_canonical_ride(...) -> [u8; 32]` helper in Rust
- expose canonicalization and hashing via PyO3
- call canonicalization from backend ride processing before attestation
- add cross-language tests proving Rust and Python produce identical bytes and
  hashes

Until those tests are green, `RideAttestation` work is not ready to ship.

---

## Future Work

Possible V2+ improvements, deliberately deferred:

- interpolation-based source normalization
- privacy-preserving committed subtraces
- segment-level canonical sub-hashes
- compression-aware binary canonical format
- signed canonicalization witness bundles

Those are future upgrades, not V1 requirements.
