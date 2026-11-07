#!/bin/bash
# build_parser.sh — build the workout-parse UniFFI bindings and stage them
# into the local WorkoutParse SwiftPM package.
#
# Run this once before the first `xcodegen generate` / build, and again after
# any change to workout-parse/. Outputs are gitignored build artifacts.
#
# Usage: bash ios/scripts/build_parser.sh [--skip-device]

set -euo pipefail
cd "$(dirname "$0")/../.."   # repo root

bash workout-parse/scripts/build_swift_bindings.sh "${1:-}"

PKG="ios/Packages/WorkoutParse"
mkdir -p "$PKG/Artifacts" "$PKG/Sources/WorkoutParse/Generated"

rm -rf "$PKG/Artifacts/WorkoutParseFFI.xcframework"
cp -R workout-parse/target/swift/WorkoutParseFFI.xcframework "$PKG/Artifacts/"
cp workout-parse/target/swift/generated/workout_parse.swift \
   "$PKG/Sources/WorkoutParse/Generated/workout_parse.swift"

echo "Staged XCFramework + generated Swift into $PKG"
