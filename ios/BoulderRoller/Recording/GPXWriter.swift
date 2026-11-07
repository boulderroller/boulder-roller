import Foundation

/// Serializes a recorded ride to GPX 1.1 using exactly the vocabulary the
/// workout-parse crate reads (see workout-parse/src/lib.rs test fixtures):
/// `gpxtpx:hr`, `gpxtpx:cad` inside TrackPointExtension, namespaced `power`.
/// The recorded file then rides the same production pipeline as any import.
enum GPXWriter {
    static func gpx(samples: [RecordedSample], startedAt: Date) -> Data {
        let timeFormatter = ISO8601DateFormatter()
        timeFormatter.formatOptions = [.withInternetDateTime]

        var out = """
        <?xml version="1.0" encoding="UTF-8"?>
        <gpx version="1.1" creator="Boulder Roller iOS"
          xmlns="http://www.topografix.com/GPX/1/1"
          xmlns:gpxtpx="http://www.garmin.com/xmlschemas/TrackPointExtension/v1"
          xmlns:br="https://boulderroller.xyz/gpx/v1">
          <metadata><time>\(timeFormatter.string(from: startedAt))</time></metadata>
          <trk><trkseg>

        """
        var lastEmittedPowerSourceID: UUID?
        for (index, s) in samples.enumerated() {
            if index > 0, s.startsNewSegment {
                out += "    </trkseg><trkseg>\n"
            }
            out += "      <trkpt lat=\"\(format(s.latitude))\" lon=\"\(format(s.longitude))\">\n"
            if let ele = s.elevationM {
                out += "        <ele>\(String(format: "%.1f", ele))</ele>\n"
            }
            out += "        <time>\(timeFormatter.string(from: s.time))</time>\n"
            let hasTpx = s.hrBpm != nil || s.cadenceRpm != nil
            let hasElevationEvidence = s.elevationSource != nil
                || s.elevationConfidence != nil
                || s.rawGPSAltitudeM != nil
                || s.relativeBarometerM != nil
            if hasTpx || s.powerW != nil || hasElevationEvidence {
                out += "        <extensions>"
                if hasTpx {
                    out += "<gpxtpx:TrackPointExtension>"
                    if let hr = s.hrBpm { out += "<gpxtpx:hr>\(hr)</gpxtpx:hr>" }
                    if let cad = s.cadenceRpm { out += "<gpxtpx:cad>\(cad)</gpxtpx:cad>" }
                    out += "</gpxtpx:TrackPointExtension>"
                }
                if let power = s.powerW {
                    out += "<br:power>\(power)</br:power>"
                    // Source switches are recorded, never silent: annotate
                    // the first powered sample and every change of meter.
                    if let sourceID = s.powerSourceID, sourceID != lastEmittedPowerSourceID {
                        out += "<br:power-source>\(sourceID.uuidString.lowercased())</br:power-source>"
                        lastEmittedPowerSourceID = sourceID
                    }
                }
                if let source = s.elevationSource {
                    out += "<br:elevation-source>\(source.rawValue)</br:elevation-source>"
                }
                if let confidence = s.elevationConfidence {
                    out += "<br:elevation-confidence>\(confidence.rawValue)</br:elevation-confidence>"
                }
                if let rawGPSAltitudeM = s.rawGPSAltitudeM {
                    out += "<br:raw-gps-altitude-m>\(String(format: "%.1f", rawGPSAltitudeM))</br:raw-gps-altitude-m>"
                }
                if let relativeBarometerM = s.relativeBarometerM {
                    out += "<br:relative-barometer-m>\(String(format: "%.1f", relativeBarometerM))</br:relative-barometer-m>"
                }
                out += "</extensions>\n"
            }
            out += "      </trkpt>\n"
        }
        out += """
          </trkseg></trk>
        </gpx>
        """
        return Data(out.utf8)
    }

    private static func format(_ coordinate: Double) -> String {
        String(format: "%.7f", coordinate)
    }
}
