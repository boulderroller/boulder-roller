import Foundation

struct RevealData: Codable, Equatable, Sendable {
    struct ClimbLine: Identifiable, Codable, Equatable, Sendable {
        let name: String
        let timeS: Double?
        let isLeaderboardEntry: Bool
        var patternID: String? = nil
        var isNewBest: Bool? = nil
        var previousBestTimeS: Double? = nil
        var id: String { patternID ?? name }
    }

    struct LeaderboardEntry: Codable, Equatable, Sendable {
        struct Seat: Identifiable, Codable, Equatable, Sendable {
            let rank: Int
            let name: String
            let timeS: Double?
            /// Only an explicit previous seat may animate displacement.
            var previousRank: Int? = nil
            var id: Int { rank }
        }
        let rank: Int
        let climbName: String
        let timeS: Double?
        /// Legacy payload field: older clients sometimes put current best
        /// here. Retained for decoding, never rendered as a previous best.
        let wasTimeS: Double?
        var previousBestTimeS: Double? = nil
        var neighboringSeats: [Seat]? = nil
    }

    struct TributeLine: Identifiable, Codable, Equatable, Sendable {
        let patternID: String
        let climbName: String
        let baseUnits: String
        let decimals: Int
        var id: String { patternID }
    }

    enum Beat: Equatable { case coin, mark, ledger }

    let title: String?
    let subtitle: String
    let calEarned: Double?
    let distanceM: Double?
    let elevationM: Double?
    let durationS: Double?
    let climbs: [ClimbLine]
    /// Decode legacy queued reveals, but never use this summed amount in UI.
    let tributeCal: Double?
    var thresholdEconomyState: String? = nil
    let leaderboardEntry: LeaderboardEntry?
    var tributeLines: [TributeLine]? = nil
    var spine: RideSpineData? = nil
    struct Verification: Codable, Equatable, Sendable {
        let status: String?
        let rideHash: String?
        let transaction: String?
    }
    var verification: Verification? = nil

    var beats: [Beat] {
        guard !climbs.isEmpty else { return [] }
        var result: [Beat] = []
        if thresholdEconomyState != "held", let calEarned, calEarned.isFinite, calEarned > 0 {
            result.append(.coin)
        }
        if let entry = leaderboardEntry, (1...10).contains(entry.rank) { result.append(.mark) }
        result.append(.ledger)
        return result
    }

    var itemizedTribute: [TributeLine] {
        (tributeLines ?? []).filter {
            !$0.climbName.isEmpty && (0...18).contains($0.decimals)
                && UInt64($0.baseUnits) != nil
        }
    }

    static func tribute(itemization: CalItemization?, climbs: [ClimbPattern]) -> [TributeLine]? {
        guard let itemization, let decimals = itemization.calDecimals,
              (0...18).contains(decimals), let shares = itemization.climbs else { return nil }
        let lines = shares.compactMap { share -> TributeLine? in
            guard let id = share.patternId, let raw = share.calTributeBaseUnits,
                  UInt64(raw) != nil,
                  let climb = climbs.first(where: { $0.id == id }) else { return nil }
            return TributeLine(patternID: id, climbName: share.climbName ?? climb.shownName, baseUnits: raw, decimals: decimals)
        }
        return lines.isEmpty ? nil : lines
    }

    /// This is display interpolation of the one ride figure. It never
    /// allocates Ride CAL to individual climbs or incorporates tribute.
    func coinFigure(completedSpans: Int) -> Double {
        let count = spine?.spans.count ?? 0
        guard count > 0 else { return calEarned ?? 0 }
        return (calEarned ?? 0) * Double(min(count, max(0, completedSpans))) / Double(count)
    }
}

/// The ledger has one ordered event stream. A climb's span and check settle
/// together, top to bottom; tribute follows, Verification arrives last.
struct RevealDrain: Equatable {
    enum Event: Equatable {
        case tick(Int)
        case settleClimb(Int)
        case settleTribute(Int)
        case verification
    }
    let climbCount: Int
    let tributeCount: Int
    private(set) var position = 0

    var events: [Event] {
        (0..<climbCount).flatMap { [Event.tick($0), .settleClimb($0)] }
            + (0..<tributeCount).map(Event.settleTribute) + [.verification]
    }
    var next: Event? { position < events.count ? events[position] : nil }
    var isStone: Bool { position >= events.count }
    var showsVerification: Bool { isStone }
    func ticked(_ index: Int) -> Bool { position > index * 2 }
    func settledClimb(_ index: Int) -> Bool { position > index * 2 + 1 }
    func settledTribute(_ index: Int) -> Bool { position > climbCount * 2 + index }
    mutating func advance() { position = min(events.count, position + 1) }
    mutating func finish() { position = events.count }
}
