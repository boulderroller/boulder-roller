import Foundation

/// Wire amounts remain strings. The only numeric/string union is the API's week.
enum Stage1JSON: Codable, Equatable {
    case string(String), number(Decimal), bool(Bool), object([String: Stage1JSON]), array([Stage1JSON]), null

    init(from decoder: Decoder) throws {
        let c = try decoder.singleValueContainer()
        if c.decodeNil() { self = .null }
        else if let v = try? c.decode(Bool.self) { self = .bool(v) }
        else if let v = try? c.decode(String.self) { self = .string(v) }
        else if let v = try? c.decode(Decimal.self) { self = .number(v) }
        else if let v = try? c.decode([String: Stage1JSON].self) { self = .object(v) }
        else { self = .array(try c.decode([Stage1JSON].self)) }
    }
    func encode(to encoder: Encoder) throws {
        if case let .object(value) = self {
            // A keyed container participates in APIClient's snake-case policy;
            // Swift Dictionary encoding deliberately bypasses that policy.
            var keyed = encoder.container(keyedBy: Key.self)
            for (key, item) in value { try keyed.encode(item, forKey: Key(stringValue: key)!) }
            return
        }
        var c = encoder.singleValueContainer()
        switch self {
        case let .string(v): try c.encode(v)
        case let .number(v): try c.encode(v)
        case let .bool(v): try c.encode(v)
        case let .object(v): try c.encode(v)
        case let .array(v): try c.encode(v)
        case .null: try c.encodeNil()
        }
    }
    private struct Key: CodingKey {
        let stringValue: String
        var intValue: Int? { nil }
        init?(stringValue: String) { self.stringValue = stringValue }
        init?(intValue: Int) { return nil }
    }
    func decode<T: Decodable>(_ type: T.Type = T.self) throws -> T {
        let decoder = JSONDecoder(); decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(type, from: JSONEncoder().encode(self))
    }
    var text: String? {
        switch self { case let .string(v): return v; case let .number(v): return "\(v)"; default: return nil }
    }
}

struct Stage1Status: Decodable {
    struct Gate: Decodable { let live: Bool?; let actions: Bool? }
    let stage1: Gate?
    var live: Bool { stage1?.live == true }
    var actionsLive: Bool { live && stage1?.actions == true }
}

struct Stage1Owner: Codable, Equatable {
    let id: String
    let wallet: String
    init(id: String, wallet: String) { self.id = id; self.wallet = wallet }
    init?(_ user: User?) {
        guard let user, !user.wallet.isEmpty else { return nil }
        self.init(id: user.id, wallet: user.wallet)
    }
    var key: String { id + ":" + wallet }
}

struct Stage1Pay: Codable {
    var climbName: String?
    var hill: String
    var week: Stage1JSON?
    var mint: String?
    var amount: String?
    var kind: String?
}
struct Stage1Payments: Decodable {
    var paid: [Stage1Pay]
    var pending: [Stage1Pay]
    var hasMore: Bool?
}
struct Stage1Registration: Decodable {
    struct Record: Decodable { let person: String; let recipient: String; let registeredAt: String }
    let registration: Record?
    let held: [Stage1Pay]
    private enum CodingKeys: String, CodingKey { case registration, held }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        guard c.contains(.registration) else {
            throw DecodingError.keyNotFound(CodingKeys.registration, .init(codingPath: decoder.codingPath, debugDescription: "Registration state absent"))
        }
        registration = try c.decodeIfPresent(Record.self, forKey: .registration)
        held = try c.decode([Stage1Pay].self, forKey: .held)
    }
}
struct Stage1Withdrawal: Codable, Identifiable {
    struct Record: Codable {
        var requestId: String?
        var lot: String?
        var exitLot: String?
        var basisLamports: String?
        var noticeAt: String?
        var eligibleAt: String?
        var status: Int?
    }
    var address: String
    var parentDepositId: String?
    var data: Record
    var id: String { address }
}
struct Stage1HillState: Codable {
    var bonded: Bool
    var foundingCutoff: String
    var foundingFreshSlots: Int
    var assetLots: [String]
}
struct Stage1CityState: Codable {
    var seasonAnchor: String
    var providerSlots: Int
    var assetCount: Int
    var intakePaused: Bool?
}
struct Stage1Asset: Codable {
    var mint: String
    var slot: Int
    var adapter: Int
    var enabled: Bool
    var admittedEpoch: String
    var lastFreshUntil: String
    var admittedNumerator: String
    var admittedDenominator: String
    var staleSince: String?
}
struct Stage1Eligibility: Codable { var refreshRate: Bool }
struct Stage1EligibilitySnapshot: Decodable {
    let actions: [String: Stage1Eligibility]
    let chainTime: String
    let week: String
    var withdrawalsPausedUntil: String?
    func applying(to lot: Stage1Pledge) throws -> Stage1Pledge {
        _ = try Stage1Numbers.required(chainTime); _ = try Stage1Numbers.required(week)
        if let withdrawalsPausedUntil { _ = try Stage1Numbers.required(withdrawalsPausedUntil) }
        var next = lot
        next.chainTime = chainTime; next.eligibilityWeek = week; next.eligibility = actions
        next.withdrawalsPausedUntil = withdrawalsPausedUntil
        return next
    }
}
struct Stage1Pledge: Codable, Identifiable {
    var climbName: String?
    var address: String
    var depositId: String?
    var hill: String
    var mint: String
    var units: String?
    var basisLamports: String?
    var lockWeeks: Int?
    var lockEnd: String?
    var founding: Bool?
    var converted: Bool?
    var cancelled: Bool?
    var exiting: Bool?
    var returnedUnits: String?
    var eligibility: [String: Stage1Eligibility]?
    var eligibilityWeek: String?
    var withdrawalsPausedUntil: String?
    var pendingRequest: String?
    var exitRequest: String?
    var sequence: String?
    var assetSlot: Int?
    var hillState: Stage1HillState?
    var cityState: Stage1CityState?
    var assetState: Stage1Asset?
    var chainTime: String?
    var chainEpoch: String?
    var withdrawals: [Stage1Withdrawal]
    var id: String { address }
    var stateLabel: String? {
        if cancelled == true { return Stage1Copy.cancelled }
        if let returned = Stage1Numbers.uint(returnedUnits), returned > 0, units == "0" { return Stage1Copy.returned }
        if exiting == true { return Stage1Copy.exiting }
        return cancelled == false && exiting == false ? Stage1Copy.active : nil
    }
}
struct Stage1Bonding: Codable {
    struct Asset: Codable {
        struct Pool: Codable { var available: String?; var pool: String?; var published: Bool? }
        var config: Stage1Asset?
        var mint: String
        var backingLamports: String?
        var backingEligible: Bool?
        var weekPool: Pool?
    }
    struct Split: Codable { var everyRiderByAscents: Int?; var topTen: Int?; var localLegend: Int? }
    var climb: String?
    var hillState: Stage1HillState?
    var cityState: Stage1CityState?
    var chainTime: String?
    var chainEpoch: String?
    var hill: String
    var bonded: Bool?
    var foundingCount: String?
    var lineLamports: String?
    var week: Stage1JSON?
    var assets: [Asset]
    var split: Split?
}

/// Only owner-read claim descriptors are decoded here. Prepare's echoed intent
/// has no representation in Stage1PreparedResponse.
struct Stage1Claim: Codable, Identifiable {
    struct Reference: Codable { let jobId: String; let role: Int; let index: Int }
    struct Descriptor: Codable {
        struct Proof: Codable { let hash: String; let sum: String }
        struct Leaf: Codable {
            let hill: String
            let week: String
            let index: UInt32
            let amountBaseUnits: String
            let proof: [Proof]
            var capBaseUnits: String?
            var frozenAt: String?
            var auditHash: String?
            var role: UInt8?
        }
        let kind: String
        let claimType: String
        let mint: String
        let claims: [Leaf]
        var single: Bool?
    }
    let reference: Reference
    let intent: Descriptor
    let requiresLookup: Bool
    var id: String { "\(reference.jobId):\(reference.role):\(reference.index)" }
}

struct Stage1PreparedResponse: Decodable {
    let preparedTransaction: PreparedVaultTransaction?
    // Deliberately no `intent`: a response cannot authorize its own bytes.
}
struct Stage1SubmitResponse: Decodable {
    struct Operation: Decodable { let operationId: String? }
    let operation: Operation?
    var withdrawalsPausedUntil: String?
}

enum Stage1Error: Error { case unavailable, disabled, actionsDisabled, wrongOwner, withdrawalsPaused }

enum Stage1Numbers {
    static func uint(_ raw: String?) -> UInt64? {
        guard let raw, !raw.isEmpty, raw == "0" || raw.first != "0",
              raw.utf8.allSatisfy({ (48...57).contains($0) }) else { return nil }
        return UInt64(raw)
    }
    static func required(_ raw: String?) throws -> UInt64 {
        guard let value = uint(raw) else { throw Stage1Error.unavailable }; return value
    }
    static func baseUnits(_ raw: String, decimals: Int, locale: Locale = .current) -> UInt64? {
        guard (0...9).contains(decimals) else { return nil }
        let separator = locale.decimalSeparator ?? "."
        let normalized = raw.replacingOccurrences(of: separator, with: ".")
        let parts = normalized.split(separator: ".", omittingEmptySubsequences: false)
        guard (1...2).contains(parts.count), !parts[0].isEmpty,
              parts.allSatisfy({ $0.utf8.allSatisfy { (48...57).contains($0) } }),
              parts.count == 1 || parts[1].count <= decimals else { return nil }
        let fraction = parts.count == 2 ? String(parts[1]) : ""
        let digits = String(parts[0]) + fraction + String(repeating: "0", count: decimals - fraction.count)
        return UInt64(digits)
    }
    static func date(_ raw: String?) -> String? {
        guard let value = uint(raw), value > 0, value <= 8_640_000_000_000 else { return nil }
        return Date(timeIntervalSince1970: Double(value)).formatted(date: .abbreviated, time: .omitted)
    }
}

struct Stage1MintRegistry {
    struct Token { let symbol: String; let decimals: Int }
    static let jito = "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn"
    static let dung = BalanceTransactionFirewall.dungMint
    static let pinned: [String: Token] = [
        jito: .init(symbol: "jitoSOL", decimals: 9),
        "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So": .init(symbol: "mSOL", decimals: 9),
        "jupSoLaHXQiZZTSfEWMTRRgpnyFm8f6sZdosWBjx93v": .init(symbol: "JupSOL", decimals: 9),
        "DpLPBaRuLnBsR3P3meU1tmiNUxreXwskXBebTYKvNGne": .init(symbol: "USDC", decimals: 6),
        "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": .init(symbol: "USDC", decimals: 6),
        BalanceTransactionFirewall.stage1CashMint: .init(symbol: "USDC", decimals: 6),
        dung: .init(symbol: "DUNG", decimals: 9),
    ]
    var testPoolMint: String?
    func token(_ mint: String) -> Token? {
        if let pinned = Self.pinned[mint] { return pinned }
        if mint == testPoolMint, (try? BalanceTransactionFirewall.decodePublicKey(mint)) != nil {
            return .init(symbol: Stage1Copy.testPool, decimals: 9)
        }
        return nil
    }
    func amount(_ raw: String?, mint: String?, kind: String? = nil) -> String? {
        guard Stage1Numbers.uint(raw) != nil else { return nil }
        let token = mint.flatMap(token) ?? (mint == nil && kind == "dung" ? Self.pinned[Self.dung] : nil)
        if let token {
            return Format.baseUnits(raw, tokenDecimals: token.decimals, decimals: token.decimals) + " " + token.symbol
        }
        guard mint != nil else { return nil }
        return Format.baseUnits(raw, tokenDecimals: 0, decimals: 0) + " " + Stage1Copy.baseUnits + " · " + Stage1Copy.unknownMint
    }
    func stakingAssets(_ bonding: Stage1Bonding) -> [Stage1Bonding.Asset] {
        guard bonding.cityState?.intakePaused == false else { return [] }
        return bonding.assets.filter { asset in
            guard let c = asset.config else { return false }
            return c.enabled && [2,3,4,5].contains(c.adapter) && token(asset.mint) != nil
        }
    }
    static func backing(_ assets: [Stage1Bonding.Asset]) -> String? {
        let eligible = assets.filter { $0.backingEligible != false }
        guard !eligible.isEmpty else { return nil }
        var total: UInt128 = 0
        for asset in eligible {
            guard let value = Stage1Numbers.uint(asset.backingLamports) else { return nil }
            let next = total.addingReportingOverflow(UInt128(value))
            guard !next.overflow else { return nil }; total = next.partialValue
        }
        return String(total)
    }
}
