// swift-tools-version: 5.9
// Local SwiftPM wrapper around the UniFFI-generated workout-parse bindings.
// The XCFramework and the generated Swift source are build artifacts
// (gitignored); run ios/scripts/build_parser.sh to produce them from the
// Rust crate. See docs/design/UNIFFI_SPIKE_FINDINGS.md.
import PackageDescription

let package = Package(
    name: "WorkoutParse",
    platforms: [.iOS(.v17)],
    products: [
        .library(name: "WorkoutParse", targets: ["WorkoutParse"])
    ],
    targets: [
        .target(
            name: "WorkoutParse",
            dependencies: ["WorkoutParseFFI"],
            path: "Sources/WorkoutParse"
        ),
        .binaryTarget(
            name: "WorkoutParseFFI",
            path: "Artifacts/WorkoutParseFFI.xcframework"
        ),
    ]
)
