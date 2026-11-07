import Foundation

/// The `/status` mobile-capabilities block (L3.04). A fixed allowlist of
/// shipped native capabilities the operator can disable in an emergency —
/// a flag can never enable an unshipped write, and unknown keys have no
/// representation here at all.
struct MobileCapabilitiesResponse: Codable, Equatable, Sendable {
    let contractVersion: String?
    let rideUpload: Bool?
    let pushRegistration: Bool?
    let profileWrites: Bool?
}

/// Client-side availability policy over the block, with a bounded cache:
/// a status read older than 15 minutes proves nothing and decays to
/// `.unknown`. Verdicts, not booleans, so surfaces must face all three
/// states explicitly.
struct MobileCapabilityPolicy: Equatable, Sendable {
    enum Capability: CaseIterable, Hashable, Sendable {
        case rideUpload
        case pushRegistration
        case profileWrites
    }

    enum Verdict: Equatable, Sendable {
        case available
        case disabled
        case unknown
    }

    /// The documented bound on how long one status read may vouch for
    /// capability state.
    static let cacheTTLS: TimeInterval = 15 * 60

    private let verdicts: [Capability: Verdict]
    let fetchedAt: Date?

    /// Cold start, before any status read: everything unknown.
    static let neverFetched = MobileCapabilityPolicy(verdicts: [:], fetchedAt: nil)

    private init(verdicts: [Capability: Verdict], fetchedAt: Date?) {
        self.verdicts = verdicts
        self.fetchedAt = fetchedAt
    }

    /// Build from one successful status read. A server that predates the
    /// block (`block == nil`) has no operator lever — the shipped default
    /// (available) is the safe default. Inside a present block, a missing
    /// field is a contract mismatch and stays unknown.
    static func from(
        block: MobileCapabilitiesResponse?, fetchedAt: Date
    ) -> MobileCapabilityPolicy {
        guard let block else {
            let all = Dictionary(
                uniqueKeysWithValues: Capability.allCases.map { ($0, Verdict.available) }
            )
            return MobileCapabilityPolicy(verdicts: all, fetchedAt: fetchedAt)
        }
        func verdict(_ flag: Bool?) -> Verdict {
            switch flag {
            case .some(true): .available
            case .some(false): .disabled
            case .none: .unknown
            }
        }
        return MobileCapabilityPolicy(
            verdicts: [
                .rideUpload: verdict(block.rideUpload),
                .pushRegistration: verdict(block.pushRegistration),
                .profileWrites: verdict(block.profileWrites),
            ],
            fetchedAt: fetchedAt
        )
    }

    func verdict(_ capability: Capability, now: Date = .now) -> Verdict {
        guard let fetchedAt,
              now.timeIntervalSince(fetchedAt) <= Self.cacheTTLS
        else { return .unknown }
        return verdicts[capability] ?? .unknown
    }

    /// Risky writes: only an explicit, fresh `available` permits.
    func allows(_ capability: Capability, now: Date = .now) -> Bool {
        verdict(capability, now: now) == .available
    }

    /// Low-risk writes (e.g. push token registration): proceed unless the
    /// operator explicitly said no — a status blip must not silently break
    /// them.
    func allowsUnlessDisabled(_ capability: Capability, now: Date = .now) -> Bool {
        verdict(capability, now: now) != .disabled
    }
}

/// Process-wide holder for the latest policy, readable from any isolation
/// (APNs callbacks are not main-actor).
final class MobileCapabilityStore: @unchecked Sendable {
    static let shared = MobileCapabilityStore()

    private let lock = NSLock()
    private var policy = MobileCapabilityPolicy.neverFetched

    func adopt(block: MobileCapabilitiesResponse?, at date: Date = .now) {
        lock.lock()
        policy = .from(block: block, fetchedAt: date)
        lock.unlock()
    }

    func current() -> MobileCapabilityPolicy {
        lock.lock()
        defer { lock.unlock() }
        return policy
    }

    /// Test seam.
    func reset() {
        lock.lock()
        policy = .neverFetched
        lock.unlock()
    }
}
