# Boulder Roller — native iOS (slice one)

Native SwiftUI app, iOS attempt #4, per `docs/design/MOBILE_RESUME_STRATEGY.md`.
Design law: `docs/design/MOBILE_DESIGN_CONSTITUTION.md` (four constants, color
ledger, row grammar, ten laws). Bead: `boulderroller-v2-dhj3d`.

## Build

Requires Xcode 26.x, Rust toolchain (for the parser), and XcodeGen.

```bash
brew install xcodegen                 # once
bash ios/scripts/build_parser.sh      # stages WorkoutParseFFI.xcframework + generated Swift
cd ios && xcodegen generate           # produces BoulderRoller.xcodeproj (gitignored)
open BoulderRoller.xcodeproj
```

Project generation choice: **XcodeGen** (`project.yml` is the committed source
of truth; the `.xcodeproj` is generated and gitignored). Chosen over a
committed project file because the manifest is reviewable text and regeneration
is deterministic — no pbxproj merge conflicts, no hidden settings drift.

## Parser

The app links the real `workout-parse/` Rust crate over UniFFI (spike:
`docs/design/UNIFFI_SPIKE_FINDINGS.md`). `ios/scripts/build_parser.sh` wraps
`workout-parse/scripts/build_swift_bindings.sh` and stages the XCFramework and
generated Swift into `Packages/WorkoutParse/` (both gitignored artifacts).
The on-device parse is a client-side preliminary read for the import flow;
the backend pipeline remains the source of truth for processing.

## Configuration

Client identifiers (Privy app id + mobile client id) are plain client-side
configuration, not secrets — they live in `BoulderRoller/App/AppConfig.swift`,
matching the values already committed in `mobile/app.config.ts`. Secrets and
invite codes are never committed; the DEBUG developer sign-in reads its invite
code from the runtime environment (`BR_DEV_INVITE_CODE` scheme variable), never
from source.

## Scope

Slice one (`boulderroller-v2-dhj3d`): onboarding + Privy auth, feed, avatar
sheet, ride sheet, climb sheet, leaderboard room, rider profile, map viewer,
share-sheet GPX/FIT import through the production pipeline, processing beat,
three-beat reveal.

Completion lane (`boulderroller-v2-fy7x2`): recording surface (Apple Workout
anatomy, live canon climb band with the app's only marquee, GPX into the same
pipeline), sensor pairing (full CoreBluetooth: HR/power/CSC), money room
(Deposit/Withdraw/Collect via Balance prepare→sign→submit, hold-to-commit
capsules), ride-contract v1 client features, app icon, states, accessibility.
Evidence: `ios/evidence/` (simulated-GPS runs labeled as such).

Still out: App Attest and map explore page. A foreground-started recording now
continues through screen lock using Core Location's background workout path;
post-termination automatic relaunch remains a separate capability from
interrupted-ride recovery on the rider's next open.
