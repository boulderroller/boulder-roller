import Foundation

/// App-facing wrapper over the UniFFI bindings (Generated/workout_parse.swift).
///
/// The on-device parse is a client-side preliminary read used by the import
/// flow; the backend pipeline remains the source of truth. Parsing is
/// blocking Rust work, so it runs off the main actor.
public enum RideFileKind: String, Sendable {
    case fit
    case gpx
    case tcx

    public init?(fileExtension: String) {
        self.init(rawValue: fileExtension.lowercased())
    }
}

public enum WorkoutParser {
    /// Parse a ride file and return the preliminary summary
    /// (canonical hash, NP/TSS/IF, tiles) via the real Rust crate.
    ///
    /// `thresholdWatts` has no default on purpose: every caller must state
    /// what the derived authority actually knows. While Threshold is
    /// Establishing, the low-level numeric ABI runs with its non-surfacing
    /// placeholder and the only two denominator-derived fields — TSS and Intensity
    /// Factor — are stripped from the result, so no number computed from a
    /// guessed threshold can ever surface or persist. Every other field
    /// (canonical hash, NP, power stats, kcals, coverage, tiles) is
    /// Threshold-independent.
    public static func preliminarySummary(
        data: Data,
        kind: RideFileKind,
        thresholdWatts: UInt16?
    ) async throws -> RideSummary {
        let thresholdForParse = thresholdWatts ?? 200
        var summary = try await Task.detached(priority: .userInitiated) {
            try parseRideSummary(
                data: data,
                fileType: kind.rawValue,
                ftpWatts: thresholdForParse,
                parserVersion: nil
            )
        }.value
        if thresholdWatts == nil {
            summary.tss = nil
            summary.intensityFactor = nil
        }
        return summary
    }

    public static var parserVersion: UInt32 { currentParserVersion() }

    /// The canonicalizer already defines an empty sample set. This explicit
    /// recorder-only entry point exposes that definition without pretending an
    /// empty GPX is parseable or uploadable.
    public static func emptyRecordingSummary(
        startedAt: Date
    ) async throws -> RideSummary {
        let startedAtMs = Int64((startedAt.timeIntervalSince1970 * 1_000).rounded())
        return try await Task.detached(priority: .userInitiated) {
            try summarizeEmptyRecording(
                startedAtMs: startedAtMs,
                parserVersion: nil
            )
        }.value
    }
}
