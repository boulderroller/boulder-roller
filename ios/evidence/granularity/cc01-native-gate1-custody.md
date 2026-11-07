# CC-01 native Gate 1 and interrupted-ride custody

Evidence date: 2026-08-11
Evidence class: local/offline simulated only

## Runnable outcome

The native recorder now creates an exact-owner (account ID plus wallet) encrypted custody record before capture, writes accepted and rejected input testimony through an atomic append-only journal, and reconstructs the same accepted samples, pause/segment state, timing domains, and sensor/elevation provenance after process reconstruction. Missing keys, corrupt evidence, unsupported versions, ownerless legacy evidence, and owner changes fail closed without assigning evidence to another rider.

Normal stop, manually paused stop, and recovered Save finalize the same immutable GPX bytes through the real Rust WorkoutParser lineage. Eligible rides persist one stable first-party upload job with both parser version and preliminary canonical hash before the existing queue reconciles it. Raw file SHA-256 remains distinct from the canonical ride hash and retries reuse the same bytes and job ID. Zero and short rides receive the real Rust-produced local stamp but remain non-uploadable under the existing 30-sample/100 m threshold; recovered riders may choose `Save Ride`, which retains the encrypted local artifact and exposes a noninteractive `Saved on this device` Feed card. Eligible recovery retains `Save & Upload`. Discard removes only the exact owner's interrupted ride.

Upload authorization, local job listing, retry, reveal claim, and reveal acknowledgement now require the captured account ID and wallet. Reveal claims and acknowledgement markers use wallet-partitioned durable paths; a valid legacy ID-only marker migrates only when its referenced immutable job proves the same wallet.

Coordinator correction also binds the live exit boundary: a failed durable suspension clears the in-memory session for owner isolation but retains the exact original timestamp, monotonic offset, state, and manifest for a real retry. Rapid duplicate Pause, Resume, and End inputs coalesce while their first transition is pending. Mid-ride location denial stops hardware and durably suspends without clearing the signed-in owner; denied hardware cannot restart from a stale control completion. A successful Cancel/exit refreshes the exact-owner AppSession custody projection before dismissal, so the interrupted Ride is offered for recovery rather than remaining a hidden row that wedges the next Record.

## Retained red to green

- Exact pre-change lane base `ff17b9ca5e1b6966eb7960dffc6b44bcb47e5341` failed the initial native Gate 1 probes: 3 tests executed with 3 expected failures. Retained output: `/tmp/br-cc01-native-gate1-red.log`. The failures bound missing first-party parser/hash lineage and missing serializable custody evidence.
- The production-used suspend-and-exit seam was retained red with 1/1 behavioral failure: suspension completed but AppSession recovery remained `nil`. Result bundle: `/tmp/br-cc01-exit-refresh-red.xcresult`; log: `/tmp/br-cc01-exit-refresh-red.log`.
- The initial suspend-fault red attempt entered simulator diagnostics before executing and is explicitly not evidence. The retained production fault test now proves the reviewed pre-change defect's corrected outcome: append failure propagates after memory isolation, earlier evidence remains intact, and retry publishes the exact original boundary rather than retry time.
- Rapid duplicate Pause uses a default-preserving injected hardware boundary, so no real authorization delegate, location updates, or timer can affect the fixture. Five consecutive arm64 repetitions passed with 0 failures/skips. Result bundle: `/tmp/br-cc01-rapid-pause-stability.xcresult`; log: `/tmp/br-cc01-rapid-pause-stability.log`.
- Final focused arm64 simulator result: 71 passed, 0 failed, 0 skipped. Result bundle: `/tmp/br-cc01-corrective-final-focused.xcresult`; log: `/tmp/br-cc01-corrective-final-focused.log`.
- Final full arm64 simulator result: 131 passed, 0 failed, 0 skipped. Result bundle: `/tmp/br-cc01-corrective-final-full.xcresult`; log: `/tmp/br-cc01-corrective-final-full.log`.
- Focused Rust empty-recording result: 2 passed, 0 failed. It proves the UniFFI wrapper matches the existing empty canonicalizer while an empty GPX remains a parse error. Log: `/tmp/br-cc01-rust-empty-summary.log`.
- Fresh Debug simulator build exited 0. Log: `/tmp/br-cc01-final-debug-build.log`.

The recurring Xcode `Supported platforms ... empty` diagnostic did not change either authoritative test result; both final xcresults report `Passed` on arm64 iPhone 17 / iOS 26.3.1.

## Exact mobile render evidence

All captures use the real production SwiftUI recovery or Feed view through one exact-owner, deterministic `#if DEBUG` fixture. They are fixture testimony, not live reads.

| State | Launch argument | Capture | SHA-256 |
|---|---|---|---|
| Eligible interrupted Ride, `Save & Upload` | `-BRRecordingRecoveryRenderFixture eligible` | `ios/evidence/granularity/cc01-recovery-save-upload-local-offline-simulated.png` | `6356902b07fb6f2e2db96be13170dae875a850b250ca8e42c5743c6672976347` |
| Ineligible interrupted Ride, `Save Ride` | `-BRRecordingRecoveryRenderFixture ineligible` | `ios/evidence/granularity/cc01-recovery-save-ride-local-offline-simulated.png` | `2e9a4c70db648900d2a2954602f2adafae1e446f678d35a39bd5c4c3de0ce565` |
| Noninteractive local Feed card, `Saved on this device` | `-BRRecordingRecoveryRenderFixture local-saved` | `ios/evidence/granularity/cc01-saved-on-device-feed-local-offline-simulated.png` | `a0fdf6506933090daf10c74a99083047328fd03adf6f8914c68b9c7ce32085bb` |

Each PNG is 1206 x 2622 from the arm64 iPhone 17 simulator. Pixel review confirms the requested state and action copy is visible without overflow. The same production views provide explicit button labels, combined local-card accessibility content, and labeled recovery metrics; the section-named native test scans the rider-facing Swift roots for the ratified naming contract and verifies the release-impossible fixture seam. This is local accessibility-structure evidence, not a physical VoiceOver session.

## Release artifact

The earlier incomplete Release bundle, generic x86_64-requesting attempt, and pre-correction replacement are rejected as final evidence. The fresh post-correction output is:

`/tmp/br-cc01-release-corrective.qRRUfK/BoulderRoller.app`

- build exited 0;
- `CFBundleExecutable` is `BoulderRoller`, and that file exists and is executable;
- executable is Mach-O arm64, 10,462,784 bytes;
- executable SHA-256 is `97531a423b79f91fd8127af7771652e682c2646ea0947e82d3ed1d7d0cf6017e`;
- Info.plist retains `com.boulderroller.app.ride-upload.reconcile` and `UIBackgroundModes = processing`;
- executable excludes `-BRRecordingRecoveryRenderFixture`, `-BRRideUploadRenderFixture`, and `-BRBalanceRenderFixture`.

Build log: `/tmp/br-cc01-corrective-release-build.log`.

## What this does not prove

No deployment, production account, authentication, upload, reveal, Balance action, rollout change, or production-data mutation occurred. Simulator reconstruction does not prove physical OS kill/reboot durability, locked-device Data Protection/Keychain behavior, background-task scheduling, real GPS/BLE testimony, network handoff, or a real ride. Those remain Tim REVIEW_DAY / `boulderroller-v2-4crx.19` physical evidence.
