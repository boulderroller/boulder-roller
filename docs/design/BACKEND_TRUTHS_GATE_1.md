# BACKEND_TRUTHS Gate 1 — Coverage Matrix

**Status:** REFERENCE — dated coverage snapshot, not current authority
**Date:** 2026-04-17
**Parent doc:** [`BACKEND_TRUTHS`](../BACKEND_TRUTHS.md)
**Tests:** `backend/tests/truths/test_backend_truths_gate1.py`

Current invariants are governed by [BACKEND_TRUTHS.md](../BACKEND_TRUTHS.md), with executable coverage in [`backend/tests/truths/test_backend_truths_gate1.py`](../../backend/tests/truths/test_backend_truths_gate1.py).

Gate 1 mirrors the protocol lane's Gate 1 / Gate 2 structure for
`PROTOCOL_TRUTHS`. Its job is to make every `BACKEND_TRUTHS` invariant that
can be programmatically verified fail the build when it regresses. Each test
cites the §N it enforces so a failing gate points a reviewer directly at the
truth that drifted.

Gate 1 is **static-scan based**. It reads backend source with `ast` + regex
and requires no Solana RPC, no Supabase, no FastAPI boot. That is deliberate:
the gate must run early in CI and must surface drift even when the full app
refuses to boot. Gate 2 (full-stack devnet smoke) is tracked separately
under the protocol lane's `backend/scripts/smoke_full_stack.py`.

Run locally:

```bash
cd backend && source venv/bin/activate
pytest tests/truths/ -v
```

---

## Coverage matrix

| § | Invariant | Test | Status |
|----|----|----|----|
| §2.2 | Ride Attestation referenced by every `credit_cal` | `test_section_2_2_every_send_credit_cal_carries_ride_hash` | PASS |
| §3.1 | `completed_at` is the economic clock (sourced from ride file) | `test_section_3_1_send_record_ride_completed_at_sourced_from_file` | PASS |
| §6.1 | Parser Version binding on every `record_ride` | `test_section_6_1_parser_version_on_every_record_ride` | PASS |
| §6.3 | Hash Compare Is The Attestation Gate | `test_section_6_3_hash_compare_is_attestation_gate` | PASS |
| §6.4 | Economic Consequences Derived Once (structural receipt guard) | `test_section_6_4_economic_send_fns_short_circuit_on_existing_receipt_pda` | PASS |
| §7.4 | Per-Bucket Carry preserved (all 5 carry fields read on-chain) | `test_section_7_4_epoch_processor_reads_all_five_carry_buckets` | PASS |
| §7.3 | Finalization One-Way (backend does not yet enforce) | `test_section_7_3_finalization_one_way_pending_backend_does_not_yet_enforce` | PENDING |
| §8.2 | Backend Authority resolved through scoped helper | `test_section_8_2_backend_authority_resolved_through_helper` | PASS |
| §10.1 | Tx construction reads RPC, not indexer | `test_section_10_1_tx_builder_reads_program_config_from_rpc_not_supabase` | PASS |
| §10.1 | Leaderboard direction (chain → DB, not DB → chain) | `test_section_10_1_leaderboard_sync_does_not_claim_db_is_source_of_truth` | PASS (landed mfab.3) |
| §10.1 | Backend runtime never calls legacy DB-native Record Board writer RPCs | `test_section_10_1_backend_runtime_does_not_call_legacy_leaderboard_writers` | PASS |
| §10.1 | Backend runtime never writes `vault_leaderboards` as truth | `test_section_10_1_backend_runtime_does_not_write_vault_leaderboards` | PASS |
| §10.1 | Live SQL chain neutralizes old leaderboard writer functions | `test_section_10_1_legacy_leaderboard_write_sql_is_neutralized` | PASS |
| §12 | Naming discipline — no unguarded `segments`/`segment_id` in response schemas | `test_section_12_no_unguarded_segments_in_response_schemas` | PASS |
| §12 | `routes/climbs.py` back-compat declaration + `/segments` alias mount | `test_section_12_climbs_route_back_compat_alias_is_documented` | PASS |

Expected roll-up on `main` today: **14 PASS, 1 SKIP (PENDING §7.3), 0 FAIL**.
(§10.1 leaderboard-direction DRIFT landed to PASS under `mfab.3`; see the
"Landed drift" section below.)

---

## Status legend

* **PASS** — the invariant holds in source today. A failing PASS test is a
  real regression; bounce the PR and fix the code.
* **PENDING** — the invariant is not yet enforced in the backend. The test
  either `skip`s or uses a sentinel scan that trips if anyone lands the
  enforcement silently without also upgrading the test. Flip to PASS when
  the underlying repair lands.
* **DRIFT (failing)** — current code violates the truth. The failure is a
  **feature** of the gate. Do not patch the test to hide the drift; patch
  the code to restore coherence.

---

## Landed drift

### §10.1 Leaderboard Direction — PASS (landed mfab.3, 2026-04-17)

Audit + fix: `docs/design/B4_LEADERBOARD_INVERSION_AUDIT.md`.

`backend/app/services/leaderboard_sync_service.py` no longer names DB as
authoritative. The module docstring now describes the flow as:

    chain (VaultLeaderboard PDA)  ->  indexer projection (indexed_leaderboards)
                                  ->  read-layer cache (vault_leaderboards)

TRUTHS context: `BACKEND_TRUTHS §10.1` (indexer is a cache), `§10.3` (drift
repair is reindex, not DB->chain write), `PROTOCOL_TRUTHS §5.1` (chain is
authoritative). The service kept its class / method names for caller
back-compat (admin routes, celery tasks, `epoch_processor`) while the
semantics were reframed from "sync DB to chain" to "verify projection vs
chain." A 0uv8 recovery-plan comment lives at the module top of file so a
future chain-field shift has a clear patch point.

Follow-up beads flagged in the audit doc:
- **FB-1:** Consolidate `vault_leaderboards` (legacy ride-processor projection)
  and `indexed_leaderboards` (chain-projected by the indexer). Structural
  lift, successor of `mfab`.
- **FB-2:** Remove `vault_leaderboards` write-side from ride-processor SQL
  (`record_vault_completion_with_best_time`) once FB-1 lands. **Landed as
  Alignment Closure (2026-04-20):** migration
  `087_retire_legacy_leaderboard_write_side.sql` drops the legacy writer
  RPCs and installs a fail-closed trigger on `vault_leaderboards`. Repair is
  reindex-from-chain; DB-native Record Board mutation is no longer a runtime
  path.
- **FB-3:** Deprecate the admin sync-status endpoints and sync log table
  once `indexed_leaderboards` is the only chain->DB arrow.

---

## Current status notes

### §6.3 Hash Compare Is The Attestation Gate — PASS (landed 2026-04-17)

**Current:** the preliminary-hash handshake is live on the backend.
`UploadInitRequest` accepts `preliminary_ride_hash` + `parser_version`,
the compare path emits named `review_reason` values, and
`services/ride_processor.py` gates economic side effects when
`requires_review=True`.

Current shape:
- FIT uploads are enforced strictly
- GPX uploads remain compatibility-safe until `boulderroller-v2-zu1z`
  lands end-to-end parity
- mismatch surfaces as `under_review`, not silent success

**Maintenance note:** when `evaluate_preliminary_attestation()` moves
fully into `services/ride_attester.py`, update the Gate 1 scan target if
needed, but keep the invariant and the PASS expectation.

## Documented PENDING gaps

### §7.3 Finalization One-Way

**Current:** the chain enforces finalization via on-chain invariants
(`RideAttestation` PDA + child receipts gated by `VaultPDA` finalised-
epoch state). The **backend** does not pre-gate `credit_cal` based on
`completed_at` vs `last_distribution_epoch`. Chain-level rejection is
the safety net.

**Flip trigger:** when `services/ride_processor.py` (or a new service)
computes `completed_at`'s epoch and refuses to call `send_credit_cal`
for a ride that falls in a finalised window, rewrite the test to assert
that gate. The sentinel scan in the PENDING test will fail if anyone
lands the gate without upgrading the test, so the test is self-
unblocking.

---

## Adding a new Gate 1 test

1. Read `BACKEND_TRUTHS.md`. Pick an invariant from §1–§13 that can be
   checked programmatically. If it needs the full app graph to verify,
   it probably belongs in Gate 2.
2. Name the test `test_section_<N>_<short_description>`. Cite the § in
   the docstring. Declare status: PASS / PENDING / DRIFT.
3. Prefer `ast`-based scans over regex when checking call shapes.
   `_helpers.py` has extraction utilities (`call_sites`,
   `is_wall_clock_call`, `refers_to_file_time`, `grep_source`).
4. Keep the scan tight. A gate that false-positives on routine edits
   gets ignored; a gate that false-negatives is worse than none.
5. Update this matrix.

---

## Gift-posture check

Before merging a change that affects a Gate 1 test, ask:

* Does the test name still cite the correct §? If the truth moved, update.
* Does the scan tolerate routine edits (rename a local variable, shuffle
  imports)? If not, tighten or loosen as appropriate.
* If the test now FAILs, is it surfacing real drift? Fix the code, not
  the test.
* If the test is PASS because the underlying function got renamed, the
  scan may have silently stopped checking. Add a sanity positive
  assertion (e.g. "expected at least one caller") so the gate cannot
  pass vacuously.
