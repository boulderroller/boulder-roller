import Foundation

/// The same additive wire fields on boards and climb-effort history.
/// No rider mass enters the display path.
protocol ClimbPowerSource {
    var avgPowerW: Double? { get }
    var powerKind: String? { get }
    var estimatedPowerW: Double? { get }
    var estimatedPowerRangeW: [Double]? { get }
    var wPerKg: Double? { get }
}

struct FormattedClimbPower: Equatable {
    let isEstimated: Bool
    let watts: String
    let range: String?
    let wattsPerKg: String?
    let accessibilityLabel: String

    var text: String { "\(isEstimated ? "≈" : "⚡") \(watts)" }
}

extension Format {
    /// Provenance must be explicit. Old responses still decode, but watts
    /// with no known kind do not become a measured or estimated claim.
    static func climbPower(_ source: some ClimbPowerSource) -> FormattedClimbPower? {
        let estimated: Bool
        switch source.powerKind {
        case "measured": estimated = false
        case "estimated": estimated = true
        default: return nil
        }
        guard let watts = estimated ? source.estimatedPowerW : source.avgPowerW,
              watts.isFinite, watts >= 0
        else { return nil }

        let value = number(watts, places: Precision.power)
        var spoken = ["\(estimated ? "Estimated" : "Measured") \(value) watts"]
        var range: String?
        if estimated, let bounds = source.estimatedPowerRangeW,
           bounds.count == 2, bounds.allSatisfy({ $0.isFinite && $0 >= 0 }),
           bounds[0] <= bounds[1] {
            let lower = number(bounds[0], places: Precision.power)
            let upper = number(bounds[1], places: Precision.power)
            range = "\(lower)–\(upper) W"
            spoken.append("range \(lower) to \(upper) watts")
        }

        // The API owns consent, including owner-only visibility. Never
        // derive this from watts and local physiology or the share switch.
        var wkg: String?
        if let ratio = source.wPerKg, ratio.isFinite, ratio >= 0 {
            let value = number(ratio, places: Precision.wattsPerKg)
            wkg = "\(value) W/kg"
            spoken.append("\(value) watts per kilogram")
        }
        return FormattedClimbPower(
            isEstimated: estimated, watts: "\(value) W", range: range,
            wattsPerKg: wkg, accessibilityLabel: spoken.joined(separator: ", ")
        )
    }
}
