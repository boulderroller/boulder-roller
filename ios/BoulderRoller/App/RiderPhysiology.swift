import Foundation

enum PhysiologySource: String, Codable, Sendable {
    case manual
    case derived
}

/// Rider-entered weight only. Threshold has its own derived authority store.
struct RiderPhysiology: Codable, Equatable, Sendable {
    var weightKg: Double?
    var weightSource: PhysiologySource?
    var weightSetAt: Date?

    static let empty = RiderPhysiology()
}

enum RiderPhysiologyStore {
    static let plausibleWeightKg: ClosedRange<Double> = 30...200

    private static func key(riderID: String) -> String {
        "br_rider_physiology_v1_\(riderID)"
    }

    static func load(
        riderID: String,
        defaults: UserDefaults = .standard
    ) -> RiderPhysiology {
        guard
            let data = defaults.data(forKey: key(riderID: riderID)),
            let decoded = try? JSONDecoder().decode(RiderPhysiology.self, from: data)
        else { return .empty }
        return decoded
    }

    @discardableResult
    static func setWeight(
        kg: Double,
        riderID: String,
        at now: Date = .now,
        defaults: UserDefaults = .standard
    ) -> Bool {
        let rounded = (kg * 10).rounded() / 10
        guard rounded.isFinite, plausibleWeightKg.contains(rounded) else { return false }
        var physiology = load(riderID: riderID, defaults: defaults)
        physiology.weightKg = rounded
        physiology.weightSource = .manual
        physiology.weightSetAt = now
        save(physiology, riderID: riderID, defaults: defaults)
        return true
    }

    static func clearWeight(riderID: String, defaults: UserDefaults = .standard) {
        var physiology = load(riderID: riderID, defaults: defaults)
        physiology.weightKg = nil
        physiology.weightSource = nil
        physiology.weightSetAt = nil
        save(physiology, riderID: riderID, defaults: defaults)
    }

    static func adoptServerWeight(
        weightKg: Double?,
        weightSource: String?,
        riderID: String,
        at now: Date = .now,
        defaults: UserDefaults = .standard
    ) {
        var physiology = load(riderID: riderID, defaults: defaults)
        guard physiology.weightKg == nil, let kg = weightKg else { return }
        let rounded = (kg * 10).rounded() / 10
        guard
            rounded.isFinite,
            plausibleWeightKg.contains(rounded),
            let source = weightSource.flatMap(PhysiologySource.init(rawValue:))
        else { return }
        physiology.weightKg = rounded
        physiology.weightSource = source
        physiology.weightSetAt = now
        save(physiology, riderID: riderID, defaults: defaults)
    }

    static func removeAccountData(
        riderID: String,
        defaults: UserDefaults = .standard
    ) {
        defaults.removeObject(forKey: key(riderID: riderID))
    }

    static func removeAccountDataRequired(
        riderID: String,
        defaults: UserDefaults = .standard
    ) throws {
        let storageKey = key(riderID: riderID)
        defaults.removeObject(forKey: storageKey)
        guard defaults.object(forKey: storageKey) == nil else {
            throw AccountDeletionLocalCleanupError.verificationFailed
        }
    }

    private static func save(
        _ physiology: RiderPhysiology,
        riderID: String,
        defaults: UserDefaults
    ) {
        guard let data = try? JSONEncoder().encode(physiology) else { return }
        defaults.set(data, forKey: key(riderID: riderID))
    }
}
