#!/bin/bash
# build_swift_bindings.sh — UniFFI Swift binding build for workout-parse.
#
# Spike deliverable for bead boulderroller-v2-8mp46. Produces:
#   target/swift/generated/          UniFFI-generated Swift + C header + modulemap
#   target/swift/include/            header + module.modulemap (XCFramework input)
#   target/swift/WorkoutParseFFI.xcframework   (ios-sim + ios device slices)
#   target/swift/harness-macos       macOS arm64 parity harness
#   target/swift/harness-ios-sim     iOS simulator arm64 parity harness
#
# All outputs land under target/ (gitignored). The Python wheel path is
# untouched: everything here uses --no-default-features --features swift.
#
# Usage: bash scripts/build_swift_bindings.sh [--skip-device]
#   --skip-device  skip the aarch64-apple-ios (physical device) slice

set -euo pipefail
cd "$(dirname "$0")/.."

SKIP_DEVICE=0
[ "${1:-}" = "--skip-device" ] && SKIP_DEVICE=1

SWIFT_OUT="target/swift"
GEN_DIR="$SWIFT_OUT/generated"
INCLUDE_DIR="$SWIFT_OUT/include"
XCFRAMEWORK="$SWIFT_OUT/WorkoutParseFFI.xcframework"

echo "== 1/6 Rust targets =="
for target in aarch64-apple-ios-sim aarch64-apple-ios aarch64-apple-darwin; do
    rustup target list --installed | grep -q "^$target$" || rustup target add "$target"
done

echo "== 2/6 macOS dylib (bindgen input) + staticlib (harness) =="
cargo build --release --no-default-features --features swift --target aarch64-apple-darwin
cargo rustc --release --no-default-features --features swift \
    --target aarch64-apple-darwin --crate-type staticlib

echo "== 3/6 UniFFI Swift bindings =="
cargo run --release --no-default-features --features swift-cli --bin uniffi-bindgen -- \
    generate --library target/aarch64-apple-darwin/release/libworkout_parse.dylib \
    --language swift --out-dir "$GEN_DIR"
mkdir -p "$INCLUDE_DIR"
cp "$GEN_DIR/workout_parseFFI.h" "$INCLUDE_DIR/"
cp "$GEN_DIR/workout_parseFFI.modulemap" "$INCLUDE_DIR/module.modulemap"

echo "== 4/6 iOS static libraries =="
cargo rustc --release --no-default-features --features swift \
    --target aarch64-apple-ios-sim --crate-type staticlib
if [ "$SKIP_DEVICE" = "0" ]; then
    cargo rustc --release --no-default-features --features swift \
        --target aarch64-apple-ios --crate-type staticlib
fi

echo "== 5/6 XCFramework =="
rm -rf "$XCFRAMEWORK"
XCARGS=(-library target/aarch64-apple-ios-sim/release/libworkout_parse.a -headers "$INCLUDE_DIR")
if [ "$SKIP_DEVICE" = "0" ]; then
    XCARGS+=(-library target/aarch64-apple-ios/release/libworkout_parse.a -headers "$INCLUDE_DIR")
fi
xcodebuild -create-xcframework "${XCARGS[@]}" -output "$XCFRAMEWORK"

echo "== 6/6 Parity harnesses =="
swiftc -O swift/harness/main.swift "$GEN_DIR/workout_parse.swift" \
    -I "$INCLUDE_DIR" -Xcc -fmodule-map-file="$INCLUDE_DIR/module.modulemap" \
    target/aarch64-apple-darwin/release/libworkout_parse.a \
    -o "$SWIFT_OUT/harness-macos"

xcrun -sdk iphonesimulator swiftc -O -target arm64-apple-ios15.0-simulator \
    swift/harness/main.swift "$GEN_DIR/workout_parse.swift" \
    -I "$INCLUDE_DIR" -Xcc -fmodule-map-file="$INCLUDE_DIR/module.modulemap" \
    target/aarch64-apple-ios-sim/release/libworkout_parse.a \
    -o "$SWIFT_OUT/harness-ios-sim"

echo
echo "Artifacts:"
ls -d "$XCFRAMEWORK"
ls -l "$SWIFT_OUT/harness-macos" "$SWIFT_OUT/harness-ios-sim"
echo
echo "Run parity:"
echo "  $SWIFT_OUT/harness-macos <ride-file>"
echo "  xcrun simctl spawn booted $SWIFT_OUT/harness-ios-sim <ride-file>   # needs a booted simulator"
