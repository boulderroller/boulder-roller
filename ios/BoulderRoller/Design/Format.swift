import Foundation
import SwiftUI

/// The rider's display unit system, from the account's server-held
/// preference. Exact meters, meters-per-second, and seconds stay internal
/// everywhere; converting them for display is arithmetic, not modeling.
/// Signed-out and ownerless surfaces read the imperial default.
enum UnitSystem: String, Sendable {
    case imperial
    case metric

    init(preferredUnits: String?) {
        self = preferredUnits == "metric" ? .metric : .imperial
    }

    /// Meters per distance display unit (statute mile / kilometer).
    var distanceUnitMeters: Double { self == .imperial ? 1609.344 : 1000 }
    var distanceUnit: String { self == .imperial ? "mi" : "km" }
    var elevationUnit: String { self == .imperial ? "ft" : "m" }
    var speedUnit: String { self == .imperial ? "mph" : "km/h" }
    /// "Miles" / "Kilometers" — chart value labels and the Units room row.
    var distanceWord: String { self == .imperial ? "Miles" : "Kilometers" }
    /// "Mile" / "Kilometer" — split rows and accessibility labels.
    var splitWord: String { self == .imperial ? "Mile" : "Kilometer" }

    func distanceValue(fromMeters m: Double) -> Double { m / distanceUnitMeters }
    func meters(fromDistanceValue v: Double) -> Double { v * distanceUnitMeters }
    func elevationValue(fromMeters m: Double) -> Double {
        self == .imperial ? m * 3.28084 : m
    }
    func speedValue(fromMps v: Double) -> Double {
        self == .imperial ? v * 2.236_936_292_1 : v * 3.6
    }
    func temperatureValue(fromCelsius c: Double) -> Double {
        self == .imperial ? c * 9 / 5 + 32 : c
    }
    var temperatureUnit: String { self == .imperial ? "°F" : "°C" }
}

extension EnvironmentValues {
    /// Display units for every rider-visible numeral; injected at the app
    /// root from the signed-in account and updated when the preference is.
    @Entry var units: UnitSystem = .imperial
}

/// The numeral precision ledger (metrics are sacred — Tim, 2026-08-21).
/// One rule per concept; every rider surface reads these through `Format`
/// and none invents its own format string. Places are display decimals.
enum Precision {
    static let distance = 1      // mi / km
    static let elevation = 0     // ft / m, thousands grouped
    static let speed = 1         // mph / km/h — stat grid and analysis alike
    static let grade = 1         // % — average, maximum, live, scrub alike
    static let power = 0         // W
    static let wattsPerKg = 2    // W/kg, matching the shared portal formatter
    static let heartRate = 0     // bpm
    static let cadence = 0       // rpm
    static let temperature = 0   // °F / °C
    static let cal = 0           // CAL display
    static let dung = 1          // DUNG display
    static let weightKg = 1      // kg (lb is whole)
}

/// Display formatting. Honors the account's preferred units wherever a
/// numeral carries one; exact base units stay internal.
enum Format {
    static let isoParser: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()

    static let isoParserNoFraction: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime]
        return f
    }()

    /// The one numeric formatter path: locale-aware grouping and decimal
    /// separator, fixed fraction digits, half-even rounding. Every numeral
    /// with a precision rule goes through here so two surfaces can never
    /// round the same value differently.
    static func number(_ value: Double, places: Int) -> String {
        guard value.isFinite else { return "—" }
        let formatter = NumberFormatter()
        formatter.numberStyle = .decimal
        formatter.minimumFractionDigits = places
        formatter.maximumFractionDigits = places
        formatter.roundingMode = .halfEven
        return formatter.string(from: NSNumber(value: value)) ?? "—"
    }

    /// Exact money uses the same locale and rounding rules without binary float.
    static func number(_ value: Decimal, places: Int, minimumPlaces: Int = 0) -> String? {
        guard !value.isNaN else { return nil }
        let formatter = NumberFormatter()
        formatter.numberStyle = .decimal
        formatter.minimumFractionDigits = minimumPlaces
        formatter.maximumFractionDigits = places
        formatter.roundingMode = .halfEven
        return formatter.string(from: NSDecimalNumber(decimal: value))
    }

    /// "6.7%" — grade at the ledger's precision, everywhere it appears.
    static func grade(_ pct: Double?) -> String {
        guard let pct else { return "—" }
        return gradeValue(pct) + "%"
    }

    /// Grade without the unit, for StatValueText value/unit slots.
    static func gradeValue(_ pct: Double) -> String {
        number(pct, places: Precision.grade)
    }

    static func date(from iso: String?) -> Date? {
        guard let iso else { return nil }
        return isoParser.date(from: iso) ?? isoParserNoFraction.date(from: iso)
    }

    /// "Saturday 7:14 AM" within the last week, "Aug 8, 2026 7:14 AM" beyond.
    /// Strava/Garmin-style fallback title when the rider hasn't named the
    /// ride (ratified by Tim 2026-08-11): place-flavored when the route
    /// preview knows where ("Manayunk Ride"), time-of-day otherwise
    /// ("Afternoon Ride"). Backend's literal default "Ride" counts as unnamed.
    static func displayRideTitle(_ title: String?, startedAtISO: String?, placeLabel: String?) -> String {
        if let title, !title.isEmpty, title != "Ride" { return title }
        if let place = placeLabel?.split(separator: ",").first.map({ $0.trimmingCharacters(in: .whitespaces) }),
           !place.isEmpty {
            return "\(place) Ride"
        }
        let hour = date(from: startedAtISO).map { Calendar.current.component(.hour, from: $0) } ?? 12
        let bucket: String
        switch hour {
        case 4..<11: bucket = "Morning"
        case 11..<14: bucket = "Lunch"
        case 14..<17: bucket = "Afternoon"
        case 17..<21: bucket = "Evening"
        default: bucket = "Night"
        }
        return "\(bucket) Ride"
    }

    static func rideTimestamp(_ iso: String?) -> String {
        guard let date = date(from: iso) else { return "" }
        let formatter = DateFormatter()
        if let days = Calendar.current.dateComponents([.day], from: date, to: .now).day,
           days < 7, days >= 0 {
            formatter.dateFormat = "EEEE h:mm a"
        } else {
            formatter.dateFormat = "MMM d, yyyy h:mm a"
        }
        return formatter.string(from: date)
    }

    /// "Aug 14" — the Threshold room's last-raised fact.
    static func monthDay(_ iso: String?) -> String {
        guard let date = date(from: iso) else { return "" }
        let formatter = DateFormatter()
        formatter.dateFormat = "MMM d"
        return formatter.string(from: date)
    }

    /// "October 2025" — the leaderboard room's carved date.
    static func monthYear(_ iso: String?) -> String {
        guard let date = date(from: iso) else { return "" }
        let formatter = DateFormatter()
        formatter.dateFormat = "MMMM yyyy"
        return formatter.string(from: date)
    }

    /// "Week of Jul 26"
    static func weekOf(_ iso: String?) -> String {
        guard let date = date(from: iso) else { return "" }
        let formatter = DateFormatter()
        formatter.dateFormat = "MMM d"
        return "Week of \(formatter.string(from: date))"
    }

    /// "12.4" — ride/climb distance in the account's units (mi or km).
    static func distance(fromMeters m: Double?, units: UnitSystem) -> String {
        guard let m else { return "—" }
        return number(units.distanceValue(fromMeters: m), places: Precision.distance)
    }

    /// "1,204" — elevation in the account's units (ft or m), whole numbers.
    static func elevation(fromMeters m: Double?, units: UnitSystem) -> String {
        guard let m else { return "—" }
        return number(units.elevationValue(fromMeters: m), places: Precision.elevation)
    }

    /// "16.3" — speed in the account's units (mph or km/h).
    static func speed(fromMps v: Double?, units: UnitSystem) -> String {
        guard let v else { return "—" }
        return number(units.speedValue(fromMps: v), places: Precision.speed)
    }

    /// "1:58" (h:mm) for card trios, "43 min" under an hour, "45 s" under a
    /// minute — a nonzero duration never reads as 0.
    static func shortDuration(_ seconds: Double?) -> String {
        guard let seconds, seconds > 0 else { return "—" }
        let total = Int(seconds.rounded())
        let h = total / 3600
        let m = (total % 3600) / 60
        if h > 0 { return "\(h):" + String(format: "%02d", m) }
        if m > 0 { return "\(m) min" }
        return "\(max(total, 1)) s"
    }

    static func clockDuration(_ seconds: Double?) -> String {
        guard let seconds, seconds > 0 else { return "—" }
        let total = Int(seconds)
        let h = total / 3600
        let m = (total % 3600) / 60
        let s = total % 60
        if h > 0 { return String(format: "%d:%02d:%02d", h, m, s) }
        return String(format: "%d:%02d", m, s)
    }

    /// "4:41" — climb and lap times at whole seconds; "1:02:05" past an hour.
    static func climbTime(_ seconds: Double?) -> String {
        guard let seconds, seconds > 0 else { return "—" }
        let total = Int(seconds.rounded())
        let h = total / 3600
        if h > 0 {
            return String(format: "%d:%02d:%02d", h, (total % 3600) / 60, total % 60)
        }
        return String(format: "%d:%02d", total / 60, total % 60)
    }

    /// CAL/DUNG display amounts from values the wire already delivered as
    /// numbers (Precision.cal / Precision.dung). Trailing zeros drop.
    static func amount(_ value: Double?, decimals: Int = Precision.cal) -> String {
        guard let value else { return "0" }
        let formatter = NumberFormatter()
        formatter.numberStyle = .decimal
        formatter.maximumFractionDigits = decimals
        formatter.minimumFractionDigits = 0
        formatter.roundingMode = .halfEven
        return formatter.string(from: NSNumber(value: value)) ?? "0"
    }

    static func amount(_ raw: String?, decimals: Int = 0) -> String {
        amount(raw.flatMap(Double.init), decimals: decimals)
    }

    /// Display amount from an exact base-units wire string (10^9 per token),
    /// divided in Decimal — never binary float — so economic figures render
    /// exactly. Display-only; exact math stays server-side.
    static func baseUnits(_ raw: String?, tokenDecimals: Int = 9, decimals: Int = Precision.cal) -> String {
        guard let raw,
              var value = Decimal(string: raw, locale: Locale(identifier: "en_US_POSIX"))
        else { return "0" }
        // Shift the decimal point exactly: 10^9 base units per token.
        value = Decimal(sign: value.sign, exponent: value.exponent - tokenDecimals,
                        significand: value.significand)
        return exactAmount("\(value)", decimals: decimals) ?? "0"
    }

    /// Exact decimal display from a server-computed units string
    /// ("12.345678901") — settlement facts never pass through binary float
    /// (L2.10). nil for absent or unparseable input, so the caller renders
    /// absence rather than a fake zero.
    static func exactAmount(_ unitsString: String?, decimals: Int = Precision.dung) -> String? {
        guard let unitsString,
              !unitsString.isEmpty,
              let value = Decimal(string: unitsString, locale: Locale(identifier: "en_US_POSIX"))
        else { return nil }
        return number(value, places: decimals)
    }

    /// "245 W" — derived Threshold row value. Absence stays absent.
    static func threshold(_ watts: Int?) -> String {
        guard let watts else { return "—" }
        return "\(watts) W"
    }

    static let poundsPerKilogram = 2.20462262185

    /// Weight row value in the account's units ("81.4 kg" / "179 lb").
    /// Kilograms are the stored truth; dash when unset.
    static func weight(kg: Double?, units: UnitSystem) -> String {
        guard let kg else { return "—" }
        if units == .metric {
            let tenths = (kg * 10).rounded() / 10
            if tenths == tenths.rounded() {
                return "\(Int(tenths)) kg"
            }
            return String(format: "%.1f kg", tenths)
        }
        return "\(Int((kg * poundsPerKilogram).rounded())) lb"
    }

    /// "0.3 mi · 9.4%" — canon grade subtitle.
    static func climbSubtitle(
        distanceM: Double?, gradientPct: Double?, units: UnitSystem
    ) -> String {
        var parts: [String] = []
        if let distanceM {
            parts.append(
                "\(Format.distance(fromMeters: distanceM, units: units)) \(units.distanceUnit)"
            )
        }
        if let gradientPct { parts.append(String(format: "%.1f%%", gradientPct)) }
        return parts.joined(separator: " · ")
    }
}
