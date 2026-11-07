import Foundation
import Testing
@testable import BoulderRoller

/// L3.10: the shareable bundle is bounded and scrubbed — tokens, emails,
/// wallets, coordinates, hashes, and ride filenames are seeded and proven
/// excluded, with the removals counted in the bundle's own report.
struct DiagnosticsBundleTests {
    private let seeded = [
        "auth ok Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.signature-blob",
        "rider someone@proton.me signed in",
        "wallet G8DM5Cjrko7qZWDX3Pmnk9UmyBH4vnrsu9K4CJz8abcd resolved",
        "fix at 40.026135, -75.229417 accepted",
        "artifact 2026-08-17-morning-ride.gpx queued",
        "hash 63a9f0ea7bb98050796b649e85481845ec684a7f2c6f4d0e9a1b2c3d4e5f6071 stamped",
    ]

    @Test func seededSecretsNeverSurviveScrubbing() {
        for line in seeded {
            let scrubbed = DiagnosticRedactor.scrub(line).text
            #expect(!scrubbed.contains("eyJ"))
            #expect(!scrubbed.contains("@proton.me"))
            #expect(!scrubbed.contains("G8DM5"))
            #expect(!scrubbed.contains("40.026135"))
            #expect(!scrubbed.contains(".gpx"))
            #expect(!scrubbed.contains("63a9f0ea"))
        }
    }

    @Test func redactionsAreCountedByKind() {
        let bundle = DiagnosticsBundle.assemble(
            appBuild: "214",
            deviceModel: "iPhone17,1",
            osVersion: "Version 26.0",
            locationAuthorization: "authorizedWhenInUse",
            notificationAuthorization: "authorized",
            connectivity: "reachable",
            capabilityVerdicts: ["rideUpload": "available"],
            rawLogs: seeded
        )
        #expect(bundle.redactions["token"] ?? 0 >= 1)
        #expect(bundle.redactions["email"] ?? 0 >= 1)
        #expect(bundle.redactions["wallet"] ?? 0 >= 1)
        #expect(bundle.redactions["coordinates"] ?? 0 >= 1)
        #expect(bundle.redactions["ride-file"] ?? 0 >= 1)
        #expect(bundle.redactions["hash"] ?? 0 >= 1)
        // The serialized bundle itself carries none of the seeded values.
        let json = bundle.asJSON
        for fragment in ["eyJ", "@proton.me", "G8DM5", "40.026135", ".gpx", "63a9f0ea"] {
            #expect(!json.contains(fragment), Comment(rawValue: fragment))
        }
    }

    @Test func bundleIsBounded() {
        let flood = (0..<1_000).map { "line \($0)" }
        let bundle = DiagnosticsBundle.assemble(
            appBuild: "214", deviceModel: "iPhone17,1", osVersion: "26",
            locationAuthorization: "denied", notificationAuthorization: "denied",
            connectivity: "unreachable", capabilityVerdicts: [:],
            rawLogs: flood
        )
        #expect(bundle.recentLogs.count == DiagnosticsBundle.maxLogEntries)
        // The newest lines win.
        #expect(bundle.recentLogs.last == "line 999")
    }

    @Test func ordinaryOperationalLinesPassThrough() {
        let line = "2026-08-20T21:00:00Z [upload] handoff paused: ride_upload capability disabled"
        let result = DiagnosticRedactor.scrub(line)
        #expect(result.text == line)
        #expect(result.counts.isEmpty)
    }
}
