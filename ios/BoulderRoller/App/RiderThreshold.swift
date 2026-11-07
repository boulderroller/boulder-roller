import Foundation

struct ThresholdSurfaceValue: Equatable, Sendable {
    let watts: Int
    let isPending: Bool
}

/// Rider-keyed cache of the server-validated Threshold authority projection.
/// A missing cache is unavailable, which is distinct from a successful
/// `Establishing` response.
enum RiderThresholdStore {
    private static let wattsRange = 50...500

    private static func key(riderID: String) -> String {
        "br_rider_threshold_v1_\(riderID)"
    }

    static func save(
        _ response: ThresholdResponse,
        riderID: String,
        now: Date = .now,
        defaults: UserDefaults = .standard
    ) -> Bool {
        guard let validatedResponse = validated(response, now: now),
              let data = try? JSONEncoder().encode(validatedResponse)
        else { return false }
        defaults.set(data, forKey: key(riderID: riderID))
        return true
    }

    static func load(
        riderID: String,
        now: Date = .now,
        defaults: UserDefaults = .standard
    ) -> ThresholdResponse? {
        guard
            let data = defaults.data(forKey: key(riderID: riderID)),
            let response = try? JSONDecoder().decode(ThresholdResponse.self, from: data)
        else { return nil }
        return validated(response, now: now)
    }

    static func clear(
        riderID: String,
        defaults: UserDefaults = .standard
    ) {
        defaults.removeObject(forKey: key(riderID: riderID))
    }

    static func display(
        riderID: String,
        now: Date = .now,
        defaults: UserDefaults = .standard
    ) -> ThresholdDisplay? {
        load(riderID: riderID, now: now, defaults: defaults).flatMap {
            display(response: $0, now: now)
        }
    }

    static func display(response: ThresholdResponse, now: Date = .now) -> ThresholdDisplay? {
        guard let response = validated(response, now: now) else { return nil }
        if response.state == "establishing" { return .establishing }
        guard let currentW = response.currentW, let establishedAt = response.establishedAt
        else { return nil }
        let pendingW = activePending(response.pendingMonday, now: now)?.watts
        return .established(
            currentW: currentW,
            establishedISO: establishedAt,
            lastRaisedISO: response.lastRaisedAt,
            pendingW: pendingW,
            pendingEffectiveISO: response.pendingMonday?.effectiveAt
        )
    }

    static func zoneThreshold(
        riderID: String,
        now: Date = .now,
        defaults: UserDefaults = .standard
    ) -> ThresholdSurfaceValue? {
        guard let response = load(riderID: riderID, now: now, defaults: defaults),
              response.state == "established",
              let currentW = response.currentW
        else { return nil }
        if let pending = activePending(response.pendingMonday, now: now) {
            return ThresholdSurfaceValue(watts: pending.watts, isPending: true)
        }
        return ThresholdSurfaceValue(watts: currentW, isPending: false)
    }

    private static func activePending(
        _ pending: ThresholdPendingMondayResponse?,
        now: Date
    ) -> ThresholdPendingMondayResponse? {
        guard let pending,
              wattsRange.contains(pending.watts),
              let effectiveAt = ISO8601DateFormatter().date(from: pending.effectiveAt),
              effectiveAt > now
        else { return nil }
        return pending
    }

    private static func suppressExpiredPending(
        _ response: ThresholdResponse,
        now: Date
    ) -> ThresholdResponse {
        guard let pending = response.pendingMonday,
              let effectiveAt = ISO8601DateFormatter().date(from: pending.effectiveAt),
              effectiveAt <= now
        else { return response }
        return ThresholdResponse(
            contractVersion: response.contractVersion,
            state: response.state,
            currentW: response.currentW,
            establishedAt: response.establishedAt,
            lastRaisedAt: response.lastRaisedAt,
            pendingMonday: nil,
            sealingInProgress: true
        )
    }

    private static func validated(
        _ response: ThresholdResponse,
        now: Date
    ) -> ThresholdResponse? {
        let response = suppressExpiredPending(response, now: now)
        guard response.contractVersion == "threshold.v1" else { return nil }
        switch response.state {
        case "establishing":
            guard response.currentW == nil,
                  response.establishedAt == nil,
                  response.lastRaisedAt == nil,
                  response.pendingMonday == nil
            else { return nil }
        case "established":
            guard let currentW = response.currentW,
                  wattsRange.contains(currentW),
                  let establishedText = response.establishedAt,
                  let establishedAt = ISO8601DateFormatter().date(from: establishedText),
                  establishedAt <= now
            else { return nil }
            if let lastRaisedText = response.lastRaisedAt {
                guard let lastRaised = ISO8601DateFormatter().date(from: lastRaisedText),
                      lastRaised > establishedAt,
                      lastRaised <= now
                else { return nil }
            }
            if let pending = response.pendingMonday {
                guard wattsRange.contains(pending.watts), pending.watts > currentW,
                      let effectiveAt = ISO8601DateFormatter().date(from: pending.effectiveAt),
                      effectiveAt > now
                else { return nil }
            }
        default:
            return nil
        }
        return response
    }
}
