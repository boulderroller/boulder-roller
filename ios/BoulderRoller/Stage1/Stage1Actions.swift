import Foundation

enum Stage1Action: String, Codable, CaseIterable {
    case registration, pledge
    case cancelPledge = "cancel-pledge", notice = "withdrawal-notice", cancelNotice = "cancel-notice"
    case beginWithdrawal = "begin-withdrawal", completeWithdrawal = "complete-withdrawal"
    case convert = "convert-pledge", selfClaim = "self-claim", transport = "claim-transport"
    var isWithdrawal: Bool { self == .beginWithdrawal || self == .completeWithdrawal }
    var label: String {
        switch self {
        case .registration: return Stage1Copy.registerAction
        case .pledge: return Stage1Copy.depositAction
        case .cancelPledge: return Stage1Copy.cancelPledgeAction
        case .notice: return Stage1Copy.noticeAction
        case .cancelNotice: return Stage1Copy.cancelNoticeAction
        case .beginWithdrawal: return Stage1Copy.beginAction
        case .completeWithdrawal: return Stage1Copy.completeAction
        case .convert: return Stage1Copy.convertAction
        case .selfClaim: return Stage1Copy.collectAction
        case .transport: return Stage1Copy.transport
        }
    }
}

struct Stage1Plan: Codable {
    let action: Stage1Action
    let request: [String: Stage1JSON]
    let intent: Stage1TransactionIntent
    var lookupTable: String?

    func reference(wallet: String) throws -> String {
        let owner = try Stage1Address.key(wallet)
        func lot(_ id: UInt64) throws -> Data { try Stage1Address.pda("s1v1_lot", owner, Stage1Address.le(id)) }
        func notice(_ id: UInt64, _ request: UInt64) throws -> Data {
            try Stage1Address.pda("s1v1_request", lot(id), Stage1Address.le(request))
        }
        let key: Data
        switch intent {
        case .registration, .cashClaim, .dungClaim: key = try Stage1Address.pda("s1v1_recipient", owner)
        case let .pledge(_, _, _, id, _, _, _, _), let .cancelPledge(_, _, id), let .convertPledge(_, _, id, _, _): key = try lot(id)
        case let .withdrawalNotice(_, id, request, _), let .cancelNotice(id, request),
             let .beginWithdrawal(_, _, id, request, _, _), let .completeWithdrawal(_, _, id, request, _, _): key = try notice(id, request)
        case let .claimTransport(_, table, _, _): return table
        }
        return Base58.encode(key)
    }
}

enum Stage1Plans {
    @MainActor static func freshLot(_ lot: Stage1Pledge, service: any Stage1Servicing, owner: Stage1Owner) async throws -> Stage1Pledge {
        let snapshot: Stage1EligibilitySnapshot = try await service.request("POST", "/stage1/me/eligibility", query: [],
            body: ["lot": .string(lot.address)], owner: owner).decode()
        return try snapshot.applying(to: lot)
    }
    struct LotAction: Identifiable {
        let action: Stage1Action
        var withdrawal: Stage1Withdrawal?
        var id: String { action.rawValue + ":" + (withdrawal?.address ?? "") }
    }
    static let locks: [UInt16] = [0, 13, 26, 52]
    static let zero = "11111111111111111111111111111111"

    static func actions(_ p: Stage1Pledge) -> [LotAction] {
        guard p.cancelled == false, let basis = Stage1Numbers.uint(p.basisLamports), basis > 0,
              let hill = p.hillState, let now = Stage1Numbers.uint(p.chainTime),
              let cutoff = Stage1Numbers.uint(hill.foundingCutoff) else { return [] }
        let active = hill.bonded && (p.exiting == true || p.converted == true ||
            Stage1Numbers.uint(p.sequence).map { $0 > cutoff } == true || p.founding == true)
        let none = p.pendingRequest == zero
        var result: [LotAction] = []
        if !active && p.exiting == false {
            result.append(.init(action: .cancelPledge))
            if hill.bonded && none && p.eligibility?[Stage1Action.convert.rawValue] != nil && p.cityState?.intakePaused == false {
                result.append(.init(action: .convert))
            }
        }
        if active && p.exiting == false && none, let lock = Stage1Numbers.uint(p.lockEnd), now >= lock {
            result.append(.init(action: .notice))
        }
        for w in p.withdrawals {
            if w.data.status == 0 && p.pendingRequest == w.address && p.exiting == false {
                result.append(.init(action: .cancelNotice, withdrawal: w))
                if active && p.withdrawalsPausedUntil == nil && p.eligibility?[Stage1Action.beginWithdrawal.rawValue] != nil,
                   let eligible = Stage1Numbers.uint(w.data.eligibleAt), now >= eligible {
                    result.append(.init(action: .beginWithdrawal, withdrawal: w))
                }
            }
            if w.data.status == 1 && p.exiting == true && p.exitRequest == w.address && w.data.exitLot == p.address && p.withdrawalsPausedUntil == nil && p.eligibility?[Stage1Action.completeWithdrawal.rawValue] != nil {
                result.append(.init(action: .completeWithdrawal, withdrawal: w))
            }
        }
        return result
    }

    static func registration(_ record: Stage1Registration) throws -> Stage1Plan {
        guard record.registration == nil else { throw Stage1Error.unavailable }
        return .init(action: .registration, request: [:], intent: .registration)
    }

    static func pledge(_ b: Stage1Bonding, registry: Stage1MintRegistry, mint: String,
                       amount: UInt64, lock: UInt16, depositID: UInt64) throws -> Stage1Plan {
        guard let climb = b.climb, let hill = b.hillState, let city = b.cityState,
              b.bonded != nil, amount > 0, locks.contains(lock),
              registry.stakingAssets(b).contains(where: { $0.mint == mint }) else { throw Stage1Error.unavailable }
        var backing: [(Int, String)] = []
        if b.bonded != true {
            for a in b.assets {
                // Sponsor cash has no staking slot; its zero `slot` is not a provider.
                guard let c = a.config, c.adapter != 254 else { continue }
                guard (0..<32).contains(c.slot) else { throw Stage1Error.unavailable }
                if city.providerSlots & (1 << c.slot) != 0 {
                    guard hill.assetLots.indices.contains(c.slot) else { throw Stage1Error.unavailable }
                    let count = try Stage1Numbers.required(hill.assetLots[c.slot])
                    if count > 0 || a.mint == mint { backing.append((c.slot, a.mint)) }
                }
            }
        }
        return .init(action: .pledge, request: ["hill": .string(b.hill), "mint": .string(mint),
            "depositId": .string(String(depositID)), "amountBaseUnits": .string(String(amount)), "lockWeeks": .number(Decimal(lock))],
            intent: .pledge(hill: b.hill, climb: climb, mint: mint, depositID: depositID, amount: amount,
                            lockWeeks: lock, bonded: b.bonded == true, backingMints: backing.sorted { $0.0 < $1.0 }.map(\.1)))
    }

    static func lot(_ p: Stage1Pledge, action: Stage1Action, lock: UInt16,
                    requestID: UInt64, withdrawal w: Stage1Withdrawal?) throws -> Stage1Plan {
        if action.isWithdrawal && p.withdrawalsPausedUntil != nil { throw Stage1Error.withdrawalsPaused }
        guard actions(p).contains(where: { $0.action == action && $0.withdrawal?.address == w?.address }), locks.contains(lock) else {
            throw Stage1Error.unavailable
        }
        let id = try Stage1Numbers.required(p.depositId)
        let refresh = p.eligibility?[action.rawValue]?.refreshRate ?? false
        var request: [String: Stage1JSON] = ["lot": .string(p.address)]
        let intent: Stage1TransactionIntent
        switch action {
        case .cancelPledge: intent = .cancelPledge(hill: p.hill, mint: p.mint, depositID: id)
        case .convert:
            request["lockWeeks"] = .number(Decimal(lock)); request["refreshRate"] = .bool(refresh)
            intent = .convertPledge(hill: p.hill, mint: p.mint, depositID: id, lockWeeks: lock, refreshRate: refresh)
        case .notice:
            let basis = try Stage1Numbers.required(p.basisLamports)
            request["requestId"] = .string(String(requestID)); request["basisLamports"] = .string(String(basis))
            intent = .withdrawalNotice(hill: p.hill, depositID: id, requestID: requestID, basisLamports: basis)
        case .cancelNotice, .beginWithdrawal, .completeWithdrawal:
            guard let w else { throw Stage1Error.unavailable }
            let rid = try Stage1Numbers.required(w.data.requestId)
            let parent = action == .completeWithdrawal ? try Stage1Numbers.required(w.parentDepositId) : id
            request["request"] = .string(w.address); request["refreshRate"] = .bool(refresh)
            if action == .cancelNotice { intent = .cancelNotice(depositID: parent, requestID: rid) }
            else {
                let week = try Stage1Numbers.required(p.eligibilityWeek)
                intent = action == .beginWithdrawal
                    ? .beginWithdrawal(hill: p.hill, mint: p.mint, depositID: parent, requestID: rid, week: week, refreshRate: refresh)
                    : .completeWithdrawal(hill: p.hill, mint: p.mint, depositID: parent, requestID: rid, week: week, refreshRate: refresh)
            }
        default: throw Stage1Error.unavailable
        }
        return .init(action: action, request: request, intent: intent)
    }

    static func claim(_ claim: Stage1Claim, lookup: String? = nil) throws -> Stage1Plan {
        let d = claim.intent
        guard d.kind == "stage1_self_claim", d.claims.count == 1 else { throw Stage1Error.unavailable }
        let raw = d.claims[0]
        let leaf = Stage1ClaimLeaf(hill: raw.hill, week: try Stage1Numbers.required(raw.week), index: raw.index,
            amount: try Stage1Numbers.required(raw.amountBaseUnits), proof: try raw.proof.map {
                guard let sum = UInt128($0.sum), String(sum) == $0.sum else { throw Stage1Error.unavailable }
                return Stage1ClaimProof(hash: try Stage1Address.hex($0.hash), sum: sum)
            })
        let intent: Stage1TransactionIntent
        if d.claimType == "cash" {
            guard let frozen = raw.frozenAt.flatMap(Int64.init), let audit = raw.auditHash else { throw Stage1Error.unavailable }
            intent = .cashClaim(mint: d.mint, leaves: [.init(leaf: leaf, cap: try Stage1Numbers.required(raw.capBaseUnits),
                frozenAt: frozen, auditHash: try Stage1Address.hex(audit))], single: lookup != nil)
        } else {
            guard d.claimType == "dung", d.mint == Stage1MintRegistry.dung, let role = raw.role else { throw Stage1Error.unavailable }
            intent = .dungClaim(leaves: [.init(leaf: leaf, role: role)], single: lookup != nil)
        }
        var request: [String: Stage1JSON] = ["claims": .array([try reference(claim)])]
        if let lookup { request["lookupTable"] = .string(lookup) }
        return .init(action: .selfClaim, request: request, intent: intent, lookupTable: lookup)
    }

    private static func reference(_ claim: Stage1Claim) throws -> Stage1JSON {
        try JSONDecoder().decode(Stage1JSON.self, from: JSONEncoder().encode(claim.reference))
    }

    static func transport(_ claim: Stage1Claim, wallet: String, slot: UInt64) throws -> Stage1Plan {
        _ = try self.claim(claim)
        guard slot <= 9_007_199_254_740_991 else { throw Stage1Error.unavailable }
        let owner = try Stage1Address.key(wallet), mint = try Stage1Address.key(claim.intent.mint)
        let leaf = claim.intent.claims[0], hill = try Stage1Address.key(leaf.hill)
        let week = Stage1Address.le(try Stage1Numbers.required(leaf.week))
        let token = try Stage1Address.key(BalanceTransactionFirewall.tokenProgram)
        let ata = try Stage1Address.derive([owner, token, mint], program: BalanceTransactionFirewall.associatedTokenProgram)
        var keys = try [Stage1Address.pda("s1v1_city"), Stage1Address.pda("s1v1_recipient", owner), mint, ata, token, Stage1Address.key(zero)]
        if claim.intent.claimType == "cash" {
            keys += try [Stage1Address.pda("s1v1_asset", mint), Stage1Address.pda("s1v1_earnings", mint), Stage1Address.pda("s1v1_claims", hill, mint, week)]
        } else {
            guard let role = leaf.role else { throw Stage1Error.unavailable }
            let dung = try Stage1Address.pda("s1v1_dung", hill, week)
            keys += try [dung, Stage1Address.pda("s1v1_dung_claims", dung, Data([role])), Stage1Address.pda("s1v1_dung_state"),
                         Stage1Address.pda("program_config"), Stage1Address.pda("dung_mint_auth")]
        }
        let addresses = Set(keys).sorted { $0.lexicographicallyPrecedes($1) }.map(Base58.encode)
        let table = Base58.encode(try Stage1Address.derive([owner, Stage1Address.le(slot)], program: Stage1Address.lookupProgram))
        return .init(action: .transport, request: ["mode": .string("create"), "claims": .array([try reference(claim)]), "recentSlot": .string(String(slot))],
            intent: .claimTransport(mode: .create, table: table, recentSlot: slot, addresses: addresses))
    }
}

enum Stage1Address {
    static let lookupProgram = "AddressLookupTab1e1111111111111111111111111"
    static func key(_ s: String) throws -> Data { try BalanceTransactionFirewall.decodePublicKey(s) }
    static func le<T: FixedWidthInteger>(_ n: T) -> Data {
        var value = n.littleEndian; return withUnsafeBytes(of: &value) { Data($0) }
    }
    static func derive(_ seeds: [Data], program: String = BalanceTransactionFirewall.boulderProgram) throws -> Data {
        guard let value = SolanaProgramAddress.canonicalAddress(seeds: seeds, program: try key(program)) else { throw Stage1Error.unavailable }
        return value
    }
    static func pda(_ seed: String, _ parts: Data...) throws -> Data { try derive([Data(seed.utf8)] + parts) }
    static func hex(_ s: String) throws -> Data {
        guard s.count == 64 else { throw Stage1Error.unavailable }
        let chars = Array(s)
        return try Data(stride(from: 0, to: 64, by: 2).map {
            guard let byte = UInt8(String(chars[$0...($0 + 1)]), radix: 16) else { throw Stage1Error.unavailable }; return byte
        })
    }
}
