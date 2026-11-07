# MOBILE_TRUTHS_GATE_1 — Coverage Summary

**Status:** HISTORICAL — Expo-era coverage matrix
**Date:** 2026-04-17
**Audience:** Mobile engineers, dispatcher, protocol agent (on return)
**Parent doc:** [MOBILE_TRUTHS](../MOBILE_TRUTHS.md)

Current enforcement is described in [MOBILE_TRUTHS.md §13.5](../MOBILE_TRUTHS.md#135-gate-1-enforcement), with native coverage in [`NativeGate1CustodyTests.swift`](../../ios/BoulderRollerTests/NativeGate1CustodyTests.swift).

---

## Purpose

MOBILE_GATE_1 is the mobile-lane analogue of the protocol agent's Gate 1
/ Gate 2 ergonomics. Every §N invariant in MOBILE_TRUTHS that can be
verified locally (without physical hardware, live network, or a
cold-booted OS) has a named test under
`mobile/src/__tests__/truths/gate1/`. When a reviewer reads the test
output, each §N invariant shows up as a labelled PASS or FAIL. A TRUTHS
regression is a Gate 1 failure.

The tests cite the §N in the test name so a failing build leads the
reader straight back to the contract in MOBILE_TRUTHS.

---

## Coverage map

| Invariant | Test(s) | Strategy |
|-----------|---------|----------|
| §3 Three Clocks — no silent conflation | three tests in `MOBILE_TRUTHS §3 Three Clocks` | Static scan of `gpsRecording.ts` for cross-domain subtraction patterns outside `sampleOffsetMsFromRideStart`; count check on helper call sites; export-presence guard. |
| §4.2 Absence vs Zero | three tests in `MOBILE_TRUTHS §4.2 Absence vs Zero` | Static scan asserts `gps_samples` sensor columns are nullable, snapshot ternary falls through to `null`, and the existing end-to-end smoke coverage in `recordingPipeline.smoke.test.ts` still names all three scenarios (markLost, registry removal, genuine zero preserved). |
| §6 Every Stop Path Stamps | three tests in `MOBILE_TRUTHS §6 Every Stop Path Stamps` | Whole-tree scan: any production file that writes `status:'stopped'` must also reference `computePreliminaryHash`. Per-module scan confirms `stopRecording` and `saveInterruptedRide` place status + hash + parser_version in the same `updateRide` call. |
| §7 Upload Boundary Atomicity | `MOBILE_TRUTHS §7 Upload Boundary Atomicity` | Brace-balanced parse of `uploadQueue.ts`: every `withTransactionSync` block that writes `upload_queue -> uploaded` also writes `rides -> uploaded`. No `status:'uploaded'` assignment exists outside a transaction block. At least two such pairings survive (409-dedup + /complete success). |
| §7 File Hash Idempotency | `MOBILE_TRUTHS §7 File Hash Idempotency` | Static scan: `createUploadEntry` uses `INSERT OR IGNORE INTO upload_queue`; no other file in the tree contains any `INSERT INTO upload_queue` variant. |
| §8 Offline Is Normal | `MOBILE_TRUTHS §8 Offline Is Normal` | Integration: drives the recording pipeline with `global.fetch` rejecting every call. Ride row is finalized with `preliminary_ride_hash` stamped and `fetch` is never called. |
| §9.1 Local Truth Encrypted At Rest | `MOBILE_TRUTHS §9.1 Local Truth Encrypted At Rest` | Static scan: `initDatabase` emits SQL statements in order, the first of which is `PRAGMA key = ...`. SQLCipher requires this before any other pragma or DDL. |
| §11 Interrupted Rides Carry Attestation | two tests in `MOBILE_TRUTHS §11 Interrupted Rides Carry Attestation` | Static scan: in `saveInterruptedRide`, the call to `computePreliminaryHash` precedes `enqueueRide`, and the `updateRide` block carries `status='stopped'` + `preliminary_ride_hash` + `parser_version` in one object literal. |
| §12 Naming discipline | `MOBILE_TRUTHS §12 Naming Discipline` | Static scan of `.tsx` under `src/screens/`: no string literal contains `workout`, `activity`, or `segment` as a whole word. Code symbols like `ActivityIndicator` are not literals and are excluded. |

---

## Invariants deferred to Gate 2 / physical rehearsal

The following clauses in MOBILE_TRUTHS are not machine-checkable in
Gate 1. They require a physical device, a real OS under memory
pressure, a live BLE sensor, or a cold-booted handset. They belong in
Gate 2 — rehearsal-style checks the dispatcher runs during the demo
hardening window — or in targeted manual rehearsals.

| Invariant | Why Gate 1 cannot assert it | Gate 2 / rehearsal handle |
|-----------|------------------------------|---------------------------|
| §2.2 Manual-pause vs auto-pause distinctness under real-world riding | Requires a rider stopping at a traffic light vs tapping pause on a real phone. | Demo rehearsal checklist. |
| §3 GPS satellite timestamp ordering under sky dropouts | Requires real GPS fix with sky degradation. | Physical ride rehearsal; Sentry watchdog for stale-gap is the closest runtime signal we ship. |
| §4.1 Low-quality geographic evidence is marked at capture time | Covered by `gpsValidation.test.ts` in unit; end-to-end requires urban-canyon GPS. | Rehearsal; acceptance check inside `docs/design/MOBILE_RESEARCH_AUDIT_2026-04-16.md`. |
| §4.3 Composed evidence never claims more than its inputs | Requires a parsed ride with a known-bad input set. | Backend-lane integration once the compare loop lands (BACKEND_TRUTHS §2.3). |
| §5.1 Rider consent to upload / earn / record | UX flow, not a runtime invariant. | Designer/PM review. |
| §7 Ride survives app suspension, phone reboot, session expiration | Requires OS-level kill + relaunch under memory pressure. | Physical rehearsal. |
| §9.2 / §9.3 Attested and Projected truth boundaries | Require a live backend round-trip. | Backend Gate 1/2 (BACKEND_TRUTHS_GATE_1) once landed. |
| §10 Authentication identity vs Protocol identity not conflated in UI | Cross-screen render-time assertion; better as a design / copy review. | UX review checklist. |
| §13.3 Server round-trips not gating rider-own-ride views | Covered statically by §8 Gate 1 for the recording pipeline. The "view-own-ride offline" surface is a designer review item. | Designer review, then one smoke in post-alpha. |

---

## Running Gate 1

```bash
cd mobile
npx jest src/__tests__/truths/gate1
```

Expected output: one named PASS per invariant, with the §N citation
right there in the describe name. A reviewer scanning the log sees the
coherence of the contract at a glance.

Gate 1 runs as part of the default `jest` invocation too — the file
lives under the standard test tree. There is no separate CI job; the
gates enforce themselves on every push.

---

## Extending Gate 1

When a new MOBILE_TRUTHS clause becomes programmatically verifiable:

1. Add a `describe('MOBILE_TRUTHS §N.M <clause name>', () => { ... })`
   block to `truths.gate1.test.ts`.
2. Write one or more tests inside that block, each named with the §N
   prefix so the failure message traces straight back to the doc.
3. If the invariant involves a new source-shape pattern, add a helper
   to the inlined helper block at the top of `truths.gate1.test.ts`
   rather than duplicating regex logic across tests. If that block
   grows beyond a handful of utilities, promote it to a sibling
   module and add an entry to jest's `testPathIgnorePatterns`.
4. Update the coverage table above.

When an invariant moves from deferred to machine-checkable (for
example, backend's compare loop lands and we can assert Attested Truth
end-to-end), migrate the row from the "deferred" table into the
"coverage map" above and add the test.
