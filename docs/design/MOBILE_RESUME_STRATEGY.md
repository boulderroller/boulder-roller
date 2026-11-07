# Mobile Resume Strategy — Native SwiftUI

**Status: Ratified by Tim 2026-08-09 and merged to main; native mobile has resumed in `ios/`.**

For the current native build, follow [`ios/README.md`](../../ios/README.md) under [MOBILE_TRUTHS.md](../MOBILE_TRUTHS.md); the original decision and build sequence are retained below.

Companion doc: [`MOBILE_DESIGN_CONSTITUTION.md`](MOBILE_DESIGN_CONSTITUTION.md)
(the full design system for the app described here).

---

## The decision

**When mobile resumes, it resumes as a native SwiftUI app — iOS attempt #4 — not
as the Expo/React Native client.** It resumes as the trusted-sensor lane, per the
ratified strategy phrase: BLE and power attestation before polish.

The Expo client (`mobile/`) is superseded for the build but **its proven pieces are
spec, not throwaway** (see "What carries over"). On ratification, `mobile/` follows
the same archive-with-era-note convention as `ios/` and `client-ios/` when the
Swift lane produces its replacement — not before.

## Why native (in priority order)

1. **One hash, one codebase — the drift bomb dies by construction.** The Expo app
   reimplemented ride canonicalization and preliminary hashing in TypeScript
   (`mobile/src/lib/canonicalize.ts`, `mobile/src/lib/preliminaryHash.ts`), so the
   §7 upload handoff depends on a TS implementation and the Rust implementation
   agreeing forever. Native binds the actual `workout-parse/` crate over UniFFI:
   the device hash and the backend hash come from the same code. This is the
   strongest argument and it is a correctness argument, not an aesthetic one.
   Spike bead: `boulderroller-v2-8mp46`.
2. **Hardware-backed attestation.** Secure Enclave + App Attest upgrade the
   Attestation Stamp from a software claim to a hardware claim. "Honest witness"
   with an Enclave signature is a better protocol, not just a classier app. This
   is the trusted-sensor thesis expressed in silicon.
3. **The platform lane is where the sensor work lives.** CoreBluetooth,
   background execution, workout sessions, and (since iOS 26) Liquid Glass are
   first-class native and perpetually bridged in React Native. The design
   constitution is deliberately built from stock SwiftUI parts — native executes
   it nearly for free; Expo would hand-rebuild it at 92% fidelity, which is the
   exact cheapness being escaped.

## What carries over from the Expo client (as spec)

Ported behaviors, in port order — Gate 1 first:

- **Gate 1 truths tests** (`mobile/__tests__/truths/gate1/`) — MOBILE_TRUTHS
  enforced clause-by-clause in CI; ported before features.
- Crash recovery for in-progress rides.
- Owner-bound encrypted ride custody (MOBILE_TRUTHS account-bound custody
  amendment, 2026-08-02).
- Attestation stamping on every stop path.
- Hash-idempotent upload queue.
- MWA + Seed Vault wallet modules — **not ported** (Android-era); noted here so
  their absence is a decision, not an oversight.

## Named trade: Android / Seeker

Swift-only defers Android indefinitely. The Seeker demo path and the Solana
Mobile Builder Grant framing lapse unless separately revived. Accepted.

## Where it lives

- **App:** fresh top-level `ios/` in this repo (name freed when the superseded
  attempts moved to `archive/` with era notes). Xcode project: BoulderRoller.
  Created by slice one, not by the spike.
- **Parser bindings:** inside `workout-parse/` — feature-gated Swift bindings
  alongside PyO3, plus the XCFramework build script. The spike touches only
  this crate.
- **Expo client:** `mobile/` stays untouched until the Swift app replaces it,
  then archives with an era note like its siblings.

## Build sequence when the lane opens

1. **Spike (already cut):** UniFFI binding for `workout-parse` — FIT parse
   on-device, hash parity with backend, PyO3 untouched.
2. App shell + theme constants (the constitution's four numbers) + Privy Swift
   auth.
3. Read surfaces against the production API: feed, ride sheet, climb sheet,
   leaderboard, profile.
4. Import via iOS share sheet → processing → reveal.
5. Money room via Boulder Roller Balance: deposit, withdraw, collect,
   settlements. Requires one backend composition: **collect-before-unstake as a
   single Balance action** so withdraw can never forfeit pending DUNG (protocol
   rule: collect first or forfeit). Cut as its own bead when this lane opens.
6. Recording + trusted-sensor lane last: GPS, background modes, BLE pairing,
   then App Attest/Enclave attestation. Hardest native work; gets a focused
   stretch, not sprint-one scraps.

First runnable slice = steps 2–4: sign in, see real rides, import a file, watch
the reveal.

## Chain note (ideation record — explicitly NOT a decision)

From the 2026-08-08 ideation: chain-of-permanence is an input to the mainnet
trigger gate (`u82.6`). Secure Enclave keys are P-256 (secp256r1) — portable to
any chain that verifies that curve (Solana's precompile; Base via RIP-7212), so
going native **keeps** the chain question open rather than closing it. No EVM
work exists, is scheduled, or is implied; re-evaluation happens only when the
mainnet trigger approaches. Rider copy never references chains either way.

## Resume trigger (historical — native lane resumed)

Tim's call, batched into weekly ratification. Candidate triggers noted without
preference: after the first real cohort settlement week lands, or an explicit
"open the lane." Until then: docs merged = direction ratified, spike may run as
a bounded experiment, no app scaffold.
