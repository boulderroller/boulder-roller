import Foundation
import MapKit
import Testing
@testable import BoulderRoller

/// Granularity 13: one cartography policy for every map surface — stock
/// standard maps, flat, muted, clutter-free; the route is the only
/// saturated element.
struct MapCartographyTests {
    @Test func snapshotConfigurationMatchesThePolicy() {
        let config = MapCartography.snapshotConfiguration()
        #expect(config.elevationStyle == .flat)
        #expect(config.emphasisStyle == .muted)
        #expect(config.pointOfInterestFilter == .excludingAll)
        #expect(config.showsTraffic == false)
    }

    /// Every live map reads MapCartography.liveStyle and no surface builds
    /// its own MKStandardMapConfiguration — drift between one map and the
    /// rest is exactly how the muted/POI policy was lost before.
    @Test func everyMapSurfaceSharesTheOneConfiguration() throws {
        let testsDirectory = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
        let appDirectory = testsDirectory
            .deletingLastPathComponent()
            .appendingPathComponent("BoulderRoller", isDirectory: true)
        let files = FileManager.default
            .enumerator(at: appDirectory, includingPropertiesForKeys: nil)?
            .compactMap { $0 as? URL }
            .filter { $0.pathExtension == "swift" } ?? []
        #expect(!files.isEmpty)
        for file in files {
            let source = try String(contentsOf: file, encoding: .utf8)
            for line in source.split(separator: "\n") where line.contains(".mapStyle(") {
                #expect(
                    line.contains(".mapStyle(MapCartography.liveStyle)"),
                    "off-policy mapStyle in \(file.lastPathComponent): \(line)"
                )
            }
            if file.lastPathComponent != "RouteMap.swift" {
                #expect(
                    !source.contains("MKStandardMapConfiguration("),
                    "private map configuration in \(file.lastPathComponent)"
                )
            }
        }
    }
}
