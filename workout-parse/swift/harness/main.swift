// Spike harness for bead boulderroller-v2-8mp46.
//
// Parses a ride file through the UniFFI-bound workout-parse crate and prints
// a deterministic key=value report. The Python twin
// (workout-parse/scripts/parity_probe.py) prints the identical report through
// the PyO3 bindings; byte-identical output is the parity proof.
//
// Float formatting: every f32 is widened to Double and printed with %.9g.
// Both sides hold the same widened double (the Rust f32 is the source of
// truth), so equal strings mean bit-identical f32 values.

import CryptoKit
import Foundation

func fmt(_ value: Float?) -> String {
    guard let value = value else { return "null" }
    return String(format: "%.9g", Double(value))
}

func fmt<T: CustomStringConvertible>(_ value: T?) -> String {
    guard let value = value else { return "null" }
    return String(describing: value)
}

let arguments = CommandLine.arguments
guard arguments.count >= 2 else {
    FileHandle.standardError.write("usage: harness <ride-file> [file-type] [ftp]\n".data(using: .utf8)!)
    exit(2)
}
let path = arguments[1]
let fileType = arguments.count >= 3 ? arguments[2] : "auto"
let ftp = arguments.count >= 4 ? UInt16(arguments[3]) ?? 200 : 200

guard let fileData = FileManager.default.contents(atPath: path) else {
    FileHandle.standardError.write("cannot read \(path)\n".data(using: .utf8)!)
    exit(2)
}

do {
    let summary = try parseRideSummary(
        data: fileData, fileType: fileType, ftpWatts: ftp, parserVersion: nil)

    let joinedTiles = summary.tileIdsRes10.joined(separator: "\n")
    let tileDigest = SHA256.hash(data: joinedTiles.data(using: .utf8)!)
        .map { String(format: "%02x", $0) }.joined()

    var lines: [String] = []
    lines.append("binding=swift-uniffi")
    lines.append("parser_version=\(summary.parserVersion)")
    lines.append("canonical_hash_hex=\(summary.canonicalHashHex)")
    lines.append("canonical_hash_raw=\(summary.canonicalHash.map { String(format: "%02x", $0) }.joined())")
    lines.append("sport=\(summary.sport)")
    lines.append("started_at_ms=\(summary.startedAtMs)")
    lines.append("total_elapsed_s=\(summary.totalElapsedS)")
    lines.append("sample_count=\(summary.sampleCount)")
    lines.append("duration_s=\(summary.durationS)")
    lines.append("moving_time_s=\(summary.movingTimeS)")
    lines.append("distance_m=\(fmt(summary.distanceM))")
    lines.append("elevation_gain_m=\(fmt(summary.elevationGainM))")
    lines.append("normalized_power_w=\(fmt(summary.normalizedPowerW))")
    lines.append("avg_power_w=\(fmt(summary.avgPowerW))")
    lines.append("max_power_w=\(fmt(summary.maxPowerW))")
    lines.append("power_sample_count=\(summary.powerSampleCount)")
    lines.append("power_sample_coverage_bps=\(summary.powerSampleCoverageBps)")
    lines.append("tss=\(fmt(summary.tss))")
    lines.append("intensity_factor=\(fmt(summary.intensityFactor))")
    lines.append("kcals=\(fmt(summary.kcals))")
    lines.append("avg_hr_bpm=\(fmt(summary.avgHrBpm))")
    lines.append("max_hr_bpm=\(fmt(summary.maxHrBpm))")
    lines.append("heart_rate_sample_count=\(summary.heartRateSampleCount)")
    lines.append("heart_rate_sample_coverage_bps=\(summary.heartRateSampleCoverageBps)")
    lines.append("avg_speed_mps=\(fmt(summary.avgSpeedMps))")
    lines.append("max_speed_mps=\(fmt(summary.maxSpeedMps))")
    lines.append("avg_cadence_rpm=\(fmt(summary.avgCadenceRpm))")
    lines.append("metrics_version=\(summary.metricsVersion)")
    lines.append("tile_count_res10=\(summary.tileCountRes10)")
    lines.append("tile_ids_sha256=\(tileDigest)")
    lines.append("first_tile=\(summary.tileIdsRes10.first ?? "null")")
    lines.append("last_tile=\(summary.tileIdsRes10.last ?? "null")")

    print(lines.joined(separator: "\n"))
} catch {
    FileHandle.standardError.write("parse failed: \(error)\n".data(using: .utf8)!)
    exit(1)
}
