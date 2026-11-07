import Foundation
import Observation

/// Stable sheet identity, matching the portal's action + record storage scope.
/// Generated deposit/request IDs and a server conflict's reference are not scope.
struct Stage1OperationScope: Codable, Hashable {
    let action: Stage1Action
    var record = ""
    var detail = ""
    var key: String { [action.rawValue, record, detail].map { "\($0.utf8.count):\($0)" }.joined() }

    init(action: Stage1Action, record: String = "", detail: String = "") {
        self.action = action; self.record = record; self.detail = detail
    }
    init(plan: Stage1Plan) throws {
        func required(_ name: String) throws -> String {
            guard let value = plan.request[name]?.text, !value.isEmpty else { throw Stage1Error.unavailable }
            return value
        }
        switch plan.action {
        case .registration: self.init(action: .registration)
        case .pledge: self.init(action: .pledge, record: try required("hill"))
        case .cancelPledge, .notice, .convert:
            self.init(action: plan.action, record: try required("lot"))
        case .cancelNotice, .beginWithdrawal, .completeWithdrawal:
            self.init(action: plan.action, record: try required("lot"), detail: try required("request"))
        case .transport:
            guard case let .claimTransport(mode, table, _, _) = plan.intent else { throw Stage1Error.unavailable }
            if mode != .create { self.init(action: .transport, record: table + mode.rawValue); return }
            self = try Self.claim(plan)
        case .selfClaim: self = try Self.claim(plan)
        }
    }
    private static func claim(_ plan: Stage1Plan) throws -> Self {
        guard let raw = plan.request["claims"] else { throw Stage1Error.unavailable }
        let refs: [Stage1Claim.Reference] = try raw.decode()
        guard let first = refs.first else { throw Stage1Error.unavailable }
        // Current sheets carry one leaf; retain distinct scopes for older bulk journals.
        let rest = refs.dropFirst().map { "\($0.jobId):\($0.role):\($0.index)" }
        return .init(action: .selfClaim, record: first.jobId,
                     detail: (["\(first.role):\(first.index)"] + rest).joined(separator: ":"))
    }
}

struct Stage1Pending: Codable {
    let owner: Stage1Owner
    let plan: Stage1Plan
    let clientRequestID: String
    var reference: String
    var signature: String?
    var blockhash: String?
    let claimID: String?
    var operationID: String?
    var conflict: Bool? = nil
    var scope: Stage1OperationScope? = nil // Absent only in the pre-scope journal.
    var withdrawalsPausedUntil: String? = nil
}

@MainActor
final class Stage1OperationStore {
    private static var signingScopes: Set<String> = []
    private let defaults: UserDefaults
    struct Completion { let confirmed: Bool; let action: Stage1Action? }
    private var completions: [String: Completion] = [:]
    init(defaults: UserDefaults = .standard) { self.defaults = defaults }
    private func key(_ owner: Stage1Owner, _ kind: String) -> String { "br-stage1:\(owner.key):\(kind)" }
    func allPending(_ owner: Stage1Owner) throws -> [Stage1Pending] {
        var rows = try defaults.data(forKey: key(owner, "pending-v2")).map {
            try JSONDecoder().decode([Stage1Pending].self, from: $0)
        } ?? []
        for p in rows {
            guard p.owner == owner, p.scope == (try Stage1OperationScope(plan: p.plan)) else { throw Stage1Error.wrongOwner }
        }
        guard Set(rows.map(\.clientRequestID)).count == rows.count else { throw Stage1Error.unavailable }
        if let data = defaults.data(forKey: key(owner, "pending")) {
            var legacy = try JSONDecoder().decode(Stage1Pending.self, from: data)
            guard legacy.owner == owner else { throw Stage1Error.wrongOwner }
            legacy.scope = try Stage1OperationScope(plan: legacy.plan)
            if let existing = rows.first(where: { $0.clientRequestID == legacy.clientRequestID }) {
                guard existing.scope == legacy.scope else { throw Stage1Error.unavailable }
            } else { rows.append(legacy) }
            // Keep both unresolved records if a legacy/new journal shares a scope.
            // Verify the replacement before removing the original bytes.
            try write(rows, owner: owner)
            defaults.removeObject(forKey: key(owner, "pending"))
        }
        return rows
    }
    func pending(_ owner: Stage1Owner, scope: Stage1OperationScope) throws -> Stage1Pending? {
        try allPending(owner).first { $0.scope == scope }
    }
    func record(_ p: Stage1Pending) throws -> Stage1Pending? {
        try allPending(p.owner).first { $0.clientRequestID == p.clientRequestID && $0.scope == p.scope }
    }
    func isCurrent(_ p: Stage1Pending) throws -> Bool {
        guard let current = try record(p) else { return false }
        let encoder = JSONEncoder(); encoder.outputFormatting = .sortedKeys
        return try encoder.encode(current) == encoder.encode(p)
    }
    func completion(_ p: Stage1Pending) -> Completion? { completions[key(p.owner, p.clientRequestID)] }
    private func write(_ rows: [Stage1Pending], owner: Stage1Owner) throws {
        let data = try JSONEncoder().encode(rows), name = key(owner, "pending-v2")
        defaults.set(data, forKey: name)
        guard defaults.data(forKey: name) == data else { throw Stage1Error.unavailable }
    }
    func save(_ pending: Stage1Pending) throws {
        guard pending.scope == (try Stage1OperationScope(plan: pending.plan)) else { throw Stage1Error.unavailable }
        var rows = try allPending(pending.owner)
        guard !rows.contains(where: { $0.scope == pending.scope || $0.clientRequestID == pending.clientRequestID }) else { throw Stage1Error.unavailable }
        rows.append(pending); try write(rows, owner: pending.owner)
    }
    @discardableResult func update(_ pending: Stage1Pending, replacing previous: Stage1Pending) throws -> Bool {
        guard pending.owner == previous.owner, pending.scope == previous.scope,
              pending.clientRequestID == previous.clientRequestID, try isCurrent(previous) else { return false }
        var rows = try allPending(pending.owner)
        guard let i = rows.firstIndex(where: { $0.clientRequestID == pending.clientRequestID && $0.scope == pending.scope }) else { return false }
        rows[i] = pending; try write(rows, owner: pending.owner); return true
    }
    @discardableResult func clear(_ pending: Stage1Pending) throws -> Bool {
        guard try isCurrent(pending) else { return false }
        var rows = try allPending(pending.owner)
        guard let i = rows.firstIndex(where: { $0.clientRequestID == pending.clientRequestID && $0.scope == pending.scope }) else { return false }
        rows.remove(at: i); try write(rows, owner: pending.owner); return true
    }
    func isSigning(_ owner: Stage1Owner, scope: Stage1OperationScope) -> Bool { Self.signingScopes.contains(key(owner, scope.key)) }
    func reserveSigning(_ owner: Stage1Owner, scope: Stage1OperationScope) throws -> Bool {
        guard try pending(owner, scope: scope) == nil else { return false }
        return Self.signingScopes.insert(key(owner, scope.key)).inserted
    }
    func releaseSigning(_ owner: Stage1Owner, scope: Stage1OperationScope) { Self.signingScopes.remove(key(owner, scope.key)) }
    func tables(_ owner: Stage1Owner) -> [String] { defaults.stringArray(forKey: key(owner, "tables")) ?? [] }
    func claimLookup(_ owner: Stage1Owner, claim: String) -> String? {
        (defaults.dictionary(forKey: key(owner, "claims")) as? [String: String])?[claim]
    }
    func clearLookup(_ owner: Stage1Owner, table: String) {
        let old = defaults.dictionary(forKey: key(owner, "claims")) as? [String: String] ?? [:]
        defaults.set(old.filter { $0.value != table }, forKey: key(owner, "claims"))
    }
    func complete(_ p: Stage1Pending, confirmed: Bool) throws {
        guard try isCurrent(p) else { return }
        if confirmed && p.conflict != true, case let .claimTransport(mode, table, _, _) = p.plan.intent {
            var inventory = tables(p.owner)
            if mode == .create {
                if !inventory.contains(table) { inventory.append(table) }
                if let claim = p.claimID {
                    var links = defaults.dictionary(forKey: key(p.owner, "claims")) as? [String: String] ?? [:]
                    links[claim] = table; defaults.set(links, forKey: key(p.owner, "claims"))
                }
            } else {
                clearLookup(p.owner, table: table)
                if mode == .close { inventory.removeAll { $0 == table } }
            }
            defaults.set(inventory, forKey: key(p.owner, "tables"))
        }
        try clear(p)
        completions[key(p.owner, p.clientRequestID)] = .init(confirmed: confirmed,
            action: confirmed && p.conflict != true ? p.plan.action : nil)
    }
}

@MainActor @Observable
final class Stage1TransactionModel {
    enum State: Equatable { case idle, working, checked, pending, delayed, needsReview, confirmed, unavailable, withdrawalsPaused }
    struct Checked {
        let plan: Stage1Plan
        let prepared: PreparedVaultTransaction
        let tables: [SolanaTransaction.ResolvedLookupTable]
        let testPool: Stage1TestPool?
    }
    private(set) var state: State = .idle
    private(set) var checked: Checked?
    private(set) var pending: Stage1Pending?
    private(set) var lastConfirmedAction: Stage1Action?
    let owner: Stage1Owner
    let scope: Stage1OperationScope
    let service: any Stage1Servicing
    let rpc: any Stage1RPCServicing
    let store: Stage1OperationStore
    private let currentOwner: () -> Stage1Owner?
    private var busy = false

    init(owner: Stage1Owner, scope: Stage1OperationScope, service: any Stage1Servicing, rpc: any Stage1RPCServicing,
         store: Stage1OperationStore, recovering: Stage1Pending? = nil, currentOwner: @escaping () -> Stage1Owner?) {
        self.owner = owner; self.service = service; self.rpc = rpc; self.store = store; self.currentOwner = currentOwner
        self.scope = scope
        do {
            if let recovering {
                guard recovering.owner == owner, recovering.scope == scope else { throw Stage1Error.wrongOwner }
                pending = recovering
            } else { pending = try store.pending(owner, scope: scope) }
            if pending != nil { state = .pending }
        }
        catch { state = .needsReview }
    }
    var isWorking: Bool { busy }
    var canPrepare: Bool { !busy && pending == nil && state != .needsReview }
    private func checkOwner() throws {
        try Task.checkCancellation()
        guard currentOwner() == owner else { throw Stage1Error.wrongOwner }
    }
    private func admission(actions: Bool = true) async throws {
        try checkOwner()
        let status = try await service.status()
        guard status.live, !actions || status.actionsLive else { throw Stage1Error.disabled }
        try checkOwner()
    }
    private func context(_ plan: Stage1Plan) async throws -> ([SolanaTransaction.ResolvedLookupTable], Stage1TestPool?) {
        var tables: [SolanaTransaction.ResolvedLookupTable] = []
        if let address = plan.lookupTable {
            guard let lookup = try await rpc.lookup(address) else { throw Stage1Error.unavailable }
            tables = [try lookup.resolved(owner: owner.wallet)]
        }
        if case let .claimTransport(mode, address, _, _) = plan.intent, mode != .create {
            guard let lookup = try await rpc.lookup(address), lookup.authority == owner.wallet,
                  mode == .deactivate ? lookup.active : !lookup.active else { throw Stage1Error.unavailable }
            // The owner inventory and prepare route check finalized SlotHashes.
            // Slot-number subtraction cannot establish the cooldown.
        }
        var mints: [String] = []
        switch plan.intent {
        case let .pledge(_, _, mint, _, _, _, _, backing): mints = [mint] + backing
        case let .cancelPledge(_, mint, _), let .convertPledge(_, mint, _, _, _),
             let .beginWithdrawal(_, mint, _, _, _, _), let .completeWithdrawal(_, mint, _, _, _, _),
             let .cashClaim(mint, _, _): mints = [mint]
        default: break
        }
        let pool = mints.contains(where: { Stage1MintRegistry.pinned[$0] == nil }) ? try await rpc.testPool() : nil
        try checkOwner(); return (tables, pool)
    }

    func prepare(_ plan: Stage1Plan) async {
        guard canPrepare else { return }
        busy = true; state = .working; checked = nil
        defer { busy = false }
        do {
            guard try Stage1OperationScope(plan: plan) == scope else { throw Stage1Error.unavailable }
            guard try store.pending(owner, scope: scope) == nil else { pending = try store.pending(owner, scope: scope); state = .pending; return }
            try await admission()
            // `plan` is a value built before this request, from inputs/owner reads.
            let response: Stage1PreparedResponse = try await service.request("POST", "/stage1/me/\(plan.action.rawValue)/prepare", query: [], body: plan.request, owner: owner).decode()
            try checkOwner()
            guard let prepared = response.preparedTransaction else { throw Stage1Error.unavailable }
            let (tables, testPool) = try await context(plan)
            try Stage1Wire.validate(prepared, plan: plan, owner: owner, tables: tables, testPool: testPool)
            checked = .init(plan: plan, prepared: prepared, tables: tables, testPool: testPool); state = .checked
        } catch APIError.http(status: _, code: "stage1_withdrawal_paused", message: _) {
            checked = nil; state = .withdrawalsPaused
        } catch { checked = nil; state = .unavailable }
    }

    /// Only the existing hold-to-commit UI invokes this method.
    func commit(claimID: String? = nil) async {
        guard !busy, let checked, pending == nil else { return }
        busy = true; state = .working
        defer { busy = false }
        do {
            guard try store.pending(owner, scope: scope) == nil else { pending = try store.pending(owner, scope: scope); state = .pending; self.checked = nil; return }
            guard try store.reserveSigning(owner, scope: scope) else { state = .unavailable; self.checked = nil; return }
            defer { store.releaseSigning(owner, scope: scope) }
            try await admission()
            let (tables, testPool) = try await context(checked.plan)
            try Stage1Wire.validate(checked.prepared, plan: checked.plan, owner: owner, tables: tables, testPool: testPool)
            if checked.plan.action.isWithdrawal {
                guard let lot = checked.plan.request["lot"]?.text else { throw Stage1Error.unavailable }
                let eligibility: Stage1EligibilitySnapshot = try await service.request("POST", "/stage1/me/eligibility",
                    query: [], body: ["lot": .string(lot)], owner: owner).decode()
                // Server UTC owns the Monday-minute window; device time never admits signing.
                if eligibility.withdrawalsPausedUntil != nil { throw Stage1Error.withdrawalsPaused }
            }
            try checkOwner()
            let signed = try await service.sign(checked.prepared.transaction, owner: owner, intent: checked.plan.intent, tables: tables, testPool: testPool)
            try checkOwner()
            // Signer must preserve the checked message and sponsor signature.
            try Stage1Wire.validateSigned(signed, original: checked.prepared.transaction)
            let p = Stage1Pending(owner: owner, plan: checked.plan, clientRequestID: "stage1-" + UUID().uuidString,
                reference: try checked.plan.reference(wallet: owner.wallet), signature: try Stage1Wire.signature(signed),
                blockhash: checked.prepared.blockhash!, claimID: claimID, scope: scope)
            try store.save(p) // Journal BEFORE send. Ambiguous replies never re-sign.
            pending = p; self.checked = nil; state = .pending
            var body = checked.plan.request
            body["signedTransaction"] = .string(signed)
            body["lastValidBlockHeight"] = .number(Decimal(checked.prepared.lastValidBlockHeight))
            body["clientRequestId"] = .string(p.clientRequestID)
            let response: Stage1SubmitResponse = try await service.request("POST", "/stage1/me/\(p.plan.action.rawValue)", query: [], body: body, owner: owner).decode()
            try checkOwner()
            var updated = p; updated.operationID = response.operation?.operationId
            updated.withdrawalsPausedUntil = response.withdrawalsPausedUntil
            try store.update(updated, replacing: p); pending = updated
        } catch Stage1Error.withdrawalsPaused {
            self.checked = nil; state = .withdrawalsPaused
        } catch let APIError.stage1OperationPending(operationID, reference) {
            guard var p = pending else { state = .needsReview; return }
            let previous = p
            p.operationID = operationID; p.reference = reference; p.signature = nil; p.blockhash = nil; p.conflict = true
            pending = p
            do { try store.update(p, replacing: previous); state = .pending } catch { state = .needsReview }
        } catch APIError.http(status: 409, code: "stage1_operation_pending", message: _) {
            // An incomplete conflict response cannot authorize retry or a
            // receipt check against the transaction the server rejected.
            if var p = pending {
                let previous = p
                p.signature = nil; p.blockhash = nil; p.conflict = true
                pending = p; _ = try? store.update(p, replacing: previous)
            }
            state = .needsReview
        } catch APIError.http(status: let status, code: let code, message: _) where [400,409,422].contains(status) && code != "stage1_operation_pending" {
            // Backend refusal before any durable operation/send.
            if let pending { _ = try? store.clear(pending) }
            pending = nil; self.checked = nil
            state = code == "stage1_withdrawal_paused" ? .withdrawalsPaused : .unavailable
        } catch { state = pending == nil ? .unavailable : .needsReview }
    }

    func reconcile() async {
        guard !busy, !store.isSigning(owner, scope: scope) else { return }
        do { try syncPending() } catch { state = .needsReview; return }
        guard let p = pending else { return }
        busy = true; defer { busy = false }
        do {
            try await admission(actions: false)
            let path = p.operationID.map { "/balance/operations/\(Stage1Model.path($0))" } ?? "/balance/operations/lookup"
            let action = "stage1_" + p.plan.action.rawValue.replacingOccurrences(of: "-", with: "_")
            let query: [URLQueryItem] = p.operationID == nil ? [
                .init(name: "reference_type", value: "stage1"), .init(name: "reference_id", value: p.reference),
                .init(name: "action_type", value: action), .init(name: "client_request_id", value: p.clientRequestID)] : []
            let status: BalanceOperationStatusResponse = try await service.request("GET", path, query: query, body: nil, owner: owner).decode()
            try checkOwner()
            guard try store.isCurrent(p) else { try syncPending(); return }
            guard status.referenceType == "stage1", status.referenceId == p.reference, status.actionType == action,
                  p.operationID == nil || p.operationID == status.operationId else { throw Stage1Error.unavailable }
            if status.recorded && !status.pending && !status.needsReview { try finish(p, confirmed: true); return }
            if status.stage1TerminalFailure == true { try finish(p, confirmed: false); return }
            state = status.needsReview ? .needsReview : status.delayed ? .delayed : .pending
            if status.needsReview { try await receipt(p) }
        } catch Stage1Error.disabled { return }
        catch {
            guard currentOwner() == owner, !Task.isCancelled else { return }
            guard (try? store.isCurrent(p)) == true else { try? syncPending(); return }
            state = .needsReview
            try? await receipt(p)
        }
    }
    private func receipt(_ p: Stage1Pending) async throws {
        guard try store.isCurrent(p) else { try syncPending(); return }
        guard p.conflict != true, let signature = p.signature, let blockhash = p.blockhash else { return }
        let result = try await rpc.settlement(signature: signature, blockhash: blockhash)
        try checkOwner()
        guard try store.isCurrent(p) else { try syncPending(); return }
        switch result { case .pending: break; case .confirmed: try finish(p, confirmed: true); case .failed: try finish(p, confirmed: false) }
    }
    private func finish(_ p: Stage1Pending, confirmed: Bool) throws {
        guard try store.isCurrent(p) else { try syncPending(); return }
        try store.complete(p, confirmed: confirmed)
        try syncPending()
    }
    private func syncPending() throws {
        if let p = pending, let current = try store.record(p) { pending = current; return }
        let previous = pending
        if let next = try store.pending(owner, scope: scope) {
            pending = next; checked = nil; lastConfirmedAction = nil; state = .pending; return
        }
        guard let previous else { return }
        let completion = store.completion(previous)
        lastConfirmedAction = completion?.action
        pending = nil; checked = nil
        state = completion.map { $0.confirmed ? .confirmed : .unavailable } ?? .idle
    }
}

enum Stage1Wire {
    private static func layout(_ base64: String) throws -> (Data, Int, Int) {
        guard let wire = Data(base64Encoded: base64), wire.count <= 1232 else { throw Stage1Error.unavailable }
        var cursor = 0
        func length() throws -> Int {
            var value = 0
            for shift in [0,7,14] {
                guard cursor < wire.count else { throw Stage1Error.unavailable }
                let byte = wire[cursor]; cursor += 1; value |= Int(byte & 127) << shift
                if byte & 128 == 0 { return value }
            }
            throw Stage1Error.unavailable
        }
        let count = try length(), signaturesStart = cursor
        guard count == 2, cursor + count * 64 + 4 < wire.count else { throw Stage1Error.unavailable }
        let start = cursor + count * 64
        cursor = start
        if wire[cursor] & 128 != 0 { cursor += 1 }
        cursor += 3
        let keys = try length(); cursor += keys * 32
        guard cursor + 32 <= wire.count, signaturesStart == 1 else { throw Stage1Error.unavailable }
        return (wire, start, cursor)
    }
    static func validate(_ prepared: PreparedVaultTransaction, plan: Stage1Plan, owner: Stage1Owner,
                         tables: [SolanaTransaction.ResolvedLookupTable], testPool: Stage1TestPool?) throws {
        try BalanceTransactionFirewall.validate(transactionB64: prepared.transaction, intent: .stage1(plan.intent, wallet: owner.wallet),
            lookupTables: tables, stage1TestPool: testPool)
        let (wire, _, hash) = try layout(prepared.transaction)
        guard prepared.lastValidBlockHeight > 0, prepared.pda == (try plan.reference(wallet: owner.wallet)),
              prepared.blockhash == Base58.encode(wire.subdata(in: hash..<hash+32)) else { throw Stage1Error.unavailable }
    }
    static func signature(_ base64: String) throws -> String {
        let (wire, _, _) = try layout(base64)
        return Base58.encode(wire.subdata(in: 1..<65))
    }
    static func validateSigned(_ signed: String, original: String) throws {
        let (wire, start, _) = try layout(signed), (prior, before, _) = try layout(original)
        guard start == before, wire.subdata(in: start..<wire.count) == prior.subdata(in: before..<prior.count),
              wire.subdata(in: 1..<65) == prior.subdata(in: 1..<65),
              wire.subdata(in: 65..<129).contains(where: { $0 != 0 }) else { throw Stage1Error.unavailable }
    }
}
