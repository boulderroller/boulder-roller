# PROTOCOL_TRUTHS_ALIGNMENT_GATE — Coverage Matrix

**Status:** REFERENCE — dated coverage snapshot, including the earlier mobile lane
**Date:** 2026-04-17
**Parent docs:**
- [`PROTOCOL_TRUTHS`](../PROTOCOL_TRUTHS.md) (canonical)
- [`MOBILE_TRUTHS`](../MOBILE_TRUTHS.md)
- [`BACKEND_TRUTHS`](../BACKEND_TRUTHS.md)
- [`MOBILE_TRUTHS_GATE_1`](./MOBILE_TRUTHS_GATE_1.md)
- [`BACKEND_TRUTHS_GATE_1`](./BACKEND_TRUTHS_GATE_1.md)

**Tests:** `backend/tests/truths/alignment/test_protocol_truths_alignment_gate.py`

Current authority is the [TRUTHS-first hierarchy](../FRESHEST_SPEC.md#source-of-truth-hierarchy), with executable alignment coverage in [`backend/tests/truths/alignment/`](../../backend/tests/truths/alignment/) and native coverage linked from [MOBILE_TRUTHS.md §13.5](../MOBILE_TRUTHS.md#135-gate-1-enforcement).

---

## Purpose

Per-lane gates (MOBILE_GATE_1, BACKEND_GATE_1) catch drift WITHIN a single
lane's TRUTHS doc. The protocol agent's own gate catches drift WITHIN
PROTOCOL_TRUTHS. This gate catches drift BETWEEN the three docs and the
code that straddles them.

If MOBILE_TRUTHS renames a clause that PROTOCOL_TRUTHS still references by
the old name, the per-lane gates pass because each one is internally
consistent — this gate is what fires.

If mobile's upload payload emits a field that backend's Pydantic model
silently drops, both per-lane gates pass (each lane is internally
consistent about its own contract) — this gate is what fires.

**The gate's job is to surface cross-lane drift, not to fix it.** When a
test here fails, the dispatcher routes the decision to Tim. Per TRUTHS
`§13.4` / MOBILE `§13.4`: the gate is an auditable contract, not an
enforcement hammer.

---

## Run locally

```bash
cd backend && source venv/bin/activate
pytest tests/truths/alignment/ -v
```

Expected output on `main` today: **17 PASS, 2 DRIFT (FAIL)**.

Each failing test's message points at BOTH sides of the drift — mobile
file:line AND backend file:line — so a reviewer lands at both halves
without hunting.

---

## Coverage matrix

### Class 1 — Doc-level consistency

| Bridge | Test | Status |
|---|---|---|
| MOBILE_TRUTHS header cites PROTOCOL_TRUTHS as parent | `test_mobile_truths_declares_it_sits_under_protocol_truths` | PASS |
| BACKEND_TRUTHS header cites PROTOCOL_TRUTHS as parent | `test_backend_truths_declares_it_sits_under_protocol_truths` | PASS |
| BACKEND_TRUTHS header cites MOBILE_TRUTHS as peer | `test_backend_truths_declares_alongside_mobile_truths` | PASS |
| Every `PROTOCOL_TRUTHS §N` citation in MOBILE_TRUTHS resolves | `test_mobile_truths_protocol_section_citations_resolve` | PASS |
| Every `PROTOCOL_TRUTHS §N` citation in BACKEND_TRUTHS resolves | `test_backend_truths_protocol_section_citations_resolve` | PASS |
| PROTOCOL_TRUTHS §11 canonical vocabulary appears in lane docs | `test_canonical_vocabulary_appears_across_lanes` | PASS |
| Deprecated term 'segment' never used as canonical object in trio | `test_no_trio_doc_uses_segment_as_canonical_object` | PASS |
| All three docs declare Status: ACTIVE | `test_all_three_truths_docs_declare_active_status` | PASS |
| MOBILE §10 ↔ BACKEND §8 wallet-vs-authority posture coheres with PROTOCOL P13 | `test_bridge_wallet_identity_cites_protocol_authority_posture` | PASS |
| MOBILE §2.4 ↔ BACKEND §6.3 both anchor on PROTOCOL §2.3 | `test_bridge_attestation_loop_cites_protocol_ride_attestation` | PASS |
| MOBILE §3.1 + BACKEND §3.1 ride-event-time bridge | `test_bridge_ride_event_time_threaded_through_both_lanes` | PASS |

### Class 2 — Cross-lane code alignment

| Bridge | Test | Status |
|---|---|---|
| Mobile `bytesToHex` produces lowercase 64-char hex | `test_mobile_preliminary_hash_serializes_as_64_char_lowercase_hex` | PASS |
| Backend `UploadInitRequest` accepts mobile-sent envelope fields | `test_backend_upload_init_accepts_mobile_sent_fields` | **DRIFT (FAIL)** |
| `parser_version` wire name agrees across lanes | `test_parser_version_wire_name_agrees_across_lanes` | **DRIFT (FAIL)** |
| `parser_version` type is plain integer on both sides | `test_parser_version_type_is_integer_on_both_sides` | PASS |
| Mobile does NOT send `completed_at` in upload envelope | `test_completed_at_is_not_a_mobile_wire_field` | PASS |
| Backend `UploadInitRequest` does NOT accept `completed_at` from body | `test_backend_upload_init_does_not_accept_completed_at_from_body` | PASS |

### Class 3 — Semantic bridge assertions

| Bridge | Test | Status |
|---|---|---|
| Attestation lineage symbols exist: MOBILE §6 → BACKEND §6.3 → PROTOCOL §2.3 | `test_attestation_lineage_path_exists_across_lanes` | PASS |
| Arrow-of-authority not inverted in any TRUTHS doc | `test_arrow_of_authority_consistent_across_lanes` | PASS |

Roll-up: **17 PASS, 2 DRIFT**.

---

## Status legend

* **PASS** — coherence holds today. A failing PASS test is a cross-lane
  regression; bounce the PR and fix the side that drifted.
* **PENDING** — coherence is expected to arrive later (e.g., a paired
  repair staged on a different bead); test uses a sentinel scan that
  trips if the underlying state changes. Currently zero PENDING tests —
  the two DRIFT tests below capture the state we'd otherwise call
  PENDING.
* **DRIFT (failing)** — current trio disagrees. Failure is the gate
  working, not a bug in the gate. Do not patch the test — patch the
  code / doc / both until the drift resolves.

---

## Known drift (today)

### DRIFT 1 — Upload envelope silently drops mobile-stamped fields

**Test:** `test_backend_upload_init_accepts_mobile_sent_fields`

Mobile's `buildUploadInitPayload()` in
`mobile/src/services/uploadQueue.ts` emits:

```ts
{ file_type, file_hash, file_size,
  parser_version?, preliminary_ride_hash? }
```

Backend's `UploadInitRequest` in `backend/app/schemas.py` declares only:

```python
class UploadInitRequest(BaseModel):
    file_type: str
    file_hash: str
    file_size: int
```

Pydantic's default `extra="ignore"` silently drops `parser_version` and
`preliminary_ride_hash`. Mobile sends them; backend never sees them.

**Why this matters:**
- BACKEND_TRUTHS §6.3: "Hash compare is the attestation gate. When the
  mobile-stamped preliminary hash is present, backend recomputation must
  match it."
- MOBILE_TRUTHS §6: "Every stop path stamps."
- Today the mobile side is already stamping. The backend cannot compare
  a hash it never receives. The §6.3 PENDING state
  ([BACKEND_TRUTHS_GATE_1](./BACKEND_TRUTHS_GATE_1.md)) is the
  backend-side view of this drift, but that matrix only sees half the
  picture. This gate surfaces the fact that the bridge is half-built.

**Decision required (Tim):** pick one of:

- **A) Tighten backend** — add `parser_version: Optional[int]` and
  `preliminary_ride_hash: Optional[str]` fields to `UploadInitRequest`,
  persist them, and wire to `ride_processor` per §6.3 progressive
  tightening. Flips BACKEND_GATE_1 §6.3 from PENDING to assertion.
- **B) Document the delay** — set `model_config = ConfigDict(extra="allow")`
  on `UploadInitRequest` with a code comment citing §6.3 progressive
  tightening. Mobile keeps sending; backend accepts-and-ignores
  explicitly until the compare path lands. Gate skips gracefully
  (the test falls through to `pytest.skip` on explicit
  `extra="allow"`).
- **C) Pull back mobile** — remove the optional fields from
  `buildUploadInitPayload` until the backend is ready. Per MOBILE_TRUTHS
  §7: "say so loudly rather than silently orphan." Today we are
  silently orphaning on the backend side.

### DRIFT 2 — `parser_version` wire name has no alias

**Test:** `test_parser_version_wire_name_agrees_across_lanes`

Mobile sends `parser_version` on the wire. Backend's internal field is
named `ride_parser_version` (per `backend/app/routes/rides.py` and
`backend/app/services/ride_processor.py`). `UploadInitRequest` declares
neither a direct `parser_version` field nor an
`AliasChoices("parser_version", "ride_parser_version")` route, so even
if DRIFT 1 were resolved with `extra="allow"`, the field would still not
bridge to the attester.

This drift compounds DRIFT 1 — resolving one without resolving the
other still leaves the bridge broken.

**Decision required (Tim):** when addressing DRIFT 1, pick the canonical
wire name:

- `parser_version` matches PROTOCOL_TRUTHS §2.3 vocabulary and is what
  mobile already sends. Backend internal column can stay
  `ride_parser_version` with an alias. This is the path of least surprise.
- Alternative: rename everything `ride_parser_version` across lanes.
  Touches mobile's `preliminaryHash.ts` and `canonicalize.ts` as well as
  backend. Larger blast radius.

---

## Scope — what this gate does NOT cover

- **In-lane invariants** — covered by MOBILE_GATE_1 and BACKEND_GATE_1.
- **On-chain / Anchor / `lib.rs`** — protocol lane, owned by the
  protocol agent's Gate 1 / Gate 2.
- **Live devnet round-trip** — integration-level, belongs in a future
  `smoke_full_stack.py`-style Gate 2.
- **Rust/TS canonicalization byte-equivalence** — already pinned by
  `mobile/src/lib/__tests__/canonicalize.test.ts` against the Rust test
  vector. This gate asserts the integer parser version matches on both
  sides; the hash-byte symmetry test is a tighter check that lives in
  the mobile suite.
- **UX copy** — language consistency in rider-facing surfaces is
  MOBILE_GATE_1's §12 naming discipline.

---

## Gift-posture design notes

Every DRIFT message names both sides of the bridge and names a
canonical fix direction or set of options. A reviewer reading only the
failure message should be able to:

1. See the mobile file/line and the backend file/line in the same error.
2. Know which TRUTHS §N the bridge maps to.
3. Have a concrete set of fix-direction choices — without the gate
   deciding for them. Tim owns the direction.

If the trio stays coherent, the gate stays quiet. Each DRIFT fails once
and stays failed until the underlying state changes — which is what
surfacing drift means.

---

## Extending the gate

When a new cross-lane invariant becomes machine-checkable:

1. Add a test to
   `backend/tests/truths/alignment/test_protocol_truths_alignment_gate.py`.
   Name it `test_<bridge_description>` with §N citations in the
   docstring.
2. If you need a new static-scan helper, add it to
   `_alignment_helpers.py` rather than inlining regex across the
   suite. Keep it cheap — static scan only, no app boot.
3. Each failure message MUST cite both sides of the bridge. "Mobile
   says X, backend says Y" is the minimum shape.
4. Update the coverage matrix above.

When a DRIFT resolves:
- Flip the table row from DRIFT to PASS.
- Leave the test in place — its permanent job is to trip if the
  resolution is ever undone.
- Update the "Known drift (today)" section to history.
