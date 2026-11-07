import Foundation

/// Backend-computed training only. None of these values authorize pay.
struct TrainingEstimate: Codable, Sendable {
    let value: Double
    let estimate: Bool
    let basis: String
    let range: [Double?]?
}

struct RideTrainingMetrics: Codable, Sendable {
    let engineVersion: Int?
    let elapsedS: Double?
    let recordingS: Double?
    let movingS: Double?
    let avgPowerW: Double?
    let maxPowerW: Double?
    let avgHrBpm: Double?
    let maxHrBpm: Double?
    let avgCadenceRpm: Double?
    let maxCadenceRpm: Double?
    let maxSpeedMps: Double?
    let avgSpeedMps: Double?
    let load: Double?
    let loadEstimate: Bool?
    let threshold: TrainingEstimate?
    let estimates: [String: TrainingEstimate?]?
    let workJ: Double?
    let caloriesKcal: Double?
    let caloriesEstimate: Bool?
    let powerZoneS: [Double]?
    let powerZoneRangesW: [[Double?]]?
    let hrZoneS: [Double]?
    let powerCurveS: [Double]?
    let powerCurveW: [Double?]?
}
