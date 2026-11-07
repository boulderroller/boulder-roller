import Foundation
import Observation

enum Stage1Load<Value> {
    case loading, unavailable, loaded(Value)
    var value: Value? { if case let .loaded(value) = self { return value }; return nil }
}

@MainActor @Observable
final class Stage1Model {
    let service: any Stage1Servicing
    let rpc: any Stage1RPCServicing
    let store: Stage1OperationStore
    private(set) var visible = false
    private(set) var actionsEnabled = false
    private(set) var owner: Stage1Owner?
    private(set) var hill: String?
    private(set) var registry = Stage1MintRegistry()
    private(set) var bonding: Stage1Load<Stage1Bonding> = .loading
    private(set) var registration: Stage1Load<Stage1Registration> = .loading
    private(set) var pay: Stage1Load<Stage1Payments> = .loading
    private(set) var dung: Stage1Load<Stage1Payments> = .loading
    private(set) var pledges: Stage1Load<[Stage1Pledge]> = .loading
    private(set) var claims: Stage1Load<[Stage1Claim]> = .loading
    private(set) var transports: Stage1Load<[Transport]> = .loaded([])
    private(set) var eligibilityFailures: Set<String> = []
    private(set) var eligibilityLoading: Set<String> = []
    private(set) var more: Set<String> = []
    private(set) var loadingMore: Set<String> = []
    private var offsets: [String: Int] = [:]
    private var generation = UUID()
    private var noHillClimbs: Set<String> = []
    private var currentClimbID: String?
    private var reconciling = false

    struct Transport: Identifiable { let id: String; let plan: Stage1Plan? }

    init(service: (any Stage1Servicing)? = nil, rpc: (any Stage1RPCServicing)? = nil,
         store: Stage1OperationStore? = nil) {
        self.service = service ?? LiveStage1Service(); self.rpc = rpc ?? Stage1RPC(); self.store = store ?? Stage1OperationStore()
    }

    func load(climbID: String?, owner: Stage1Owner?) async {
        generation = UUID(); let epoch = generation
        currentClimbID = climbID
        visible = false; actionsEnabled = false; self.owner = owner; hill = nil
        bonding = .loading; registration = .loading; pay = .loading; dung = .loading
        pledges = .loading; claims = .loading; transports = .loaded([])
        more = []; loadingMore = []; offsets = [:]; eligibilityFailures = []; eligibilityLoading = []; registry = .init()
        async let recovery = reconcilePending()
        await loadReads(climbID: climbID, owner: owner, epoch: epoch)
        _ = await recovery
    }

    private func loadReads(climbID: String?, owner: Stage1Owner?, epoch: UUID) async {
        guard valid(epoch), !hasNoHill(climbID) else { return }
        do {
            let status = try await service.status()
            guard status.live, valid(epoch) else { return }
            visible = true; actionsEnabled = status.actionsLive
            struct Mints: Decodable { let testPoolMint: String? }
            if let mints: Mints = await read("/stage1/mints", owner: nil).value, valid(epoch), visible { registry.testPoolMint = mints.testPoolMint }
            guard valid(epoch), visible else { return }
            if let climbID {
                struct Hill: Decodable {
                    let hill: String?
                    private enum CodingKeys: String, CodingKey { case hill }
                    init(from decoder: Decoder) throws {
                        let c = try decoder.container(keyedBy: CodingKeys.self)
                        guard c.contains(.hill) else { throw Stage1Error.unavailable }
                        hill = try c.decodeIfPresent(String.self, forKey: .hill)
                    }
                }
                let response: Stage1Load<Hill> = await read("/stage1/climbs/\(Self.path(climbID))/hill", owner: nil)
                guard valid(epoch), visible else { return }
                switch response {
                case let .loaded(value):
                    guard let hill = value.hill else { noHillClimbs.insert(climbID); visible = false; return }
                    self.hill = hill
                default: bonding = .unavailable; return
                }
                let nextBonding: Stage1Load<Stage1Bonding> = await read("/stage1/hills/\(Self.path(hill!))/bonding", owner: nil)
                guard valid(epoch), visible else { return }
                bonding = nextBonding
            }
            guard valid(epoch), visible, owner != nil else { return }
            async let r: Stage1Load<Stage1Registration> = read("/stage1/me/registration", query: hillQuery, owner: owner)
            async let p: Stage1Load<Stage1Payments> = read("/stage1/me/pay", query: pageQuery(0), owner: owner)
            async let d: Stage1Load<Stage1Payments> = read("/stage1/me/dung", query: pageQuery(0), owner: owner)
            async let lots: Stage1Load<Pledges> = read("/stage1/me/pledges", query: pageQuery(0), owner: owner)
            async let leaves: Stage1Load<Claims> = actionsEnabled ? read("/stage1/me/claims", query: Self.claimsPage(0), owner: owner) : .loaded(.init(claims: [], nextOffset: nil))
            let (registration, pay, dung, pledges, claims) = await (r, p, d, lots, leaves)
            guard valid(epoch), visible else { return }
            self.registration = registration; self.pay = pay; self.dung = dung
            for (kind, page) in [("pay", pay.value), ("dung", dung.value)] {
                if let page, page.hasMore ?? (max(page.paid.count, page.pending.count) == 50) { more.insert(kind); offsets[kind] = 50 }
            }
            if let page = pledges.value {
                self.pledges = .loaded(page.pledges.map(Self.withoutEligibility))
                if page.pledges.count == 50 { more.insert("pledges"); offsets["pledges"] = 50 }
            } else { self.pledges = .unavailable }
            guard valid(epoch), visible else { return }
            if let page = claims.value {
                self.claims = .loaded(page.claims)
                if let next = page.nextOffset, next > 0 { more.insert("claims"); offsets["claims"] = next }
            } else { self.claims = .unavailable }
            if actionsEnabled { await loadTransports() }
        } catch { if valid(epoch) { visible = false } }
    }

    func refreshGate() async -> Bool {
        guard !hasNoHill(currentClimbID) else { return false }
        let epoch = generation
        do {
            let status = try await service.status()
            guard valid(epoch) else { return false }
            actionsEnabled = status.actionsLive
            if !status.live { visible = false }
            return status.live
        } catch { if valid(epoch) { visible = false; actionsEnabled = false }; return false }
    }
    func hasNoHill(_ climbID: String?) -> Bool { climbID.map(noHillClimbs.contains) ?? false }

    /// Runs from the mounted section, including when every action sheet is closed.
    /// Enumerate the durable owner journal, not just records on the current page.
    @discardableResult func reconcilePending() async -> Bool {
        guard !reconciling, let owner, let rows = try? store.allPending(owner), !rows.isEmpty else { return false }
        reconciling = true; defer { reconciling = false }
        let epoch = generation
        var changed = false
        for p in rows {
            guard valid(epoch), let scope = p.scope else { break }
            let recovery = Stage1TransactionModel(owner: owner, scope: scope, service: service, rpc: rpc,
                store: store, recovering: p, currentOwner: { [weak self] in
                    guard let self, self.valid(epoch) else { return nil }; return self.owner
                })
            await recovery.reconcile()
            guard valid(epoch) else { return false }
            if let remaining = try? store.allPending(owner), !remaining.contains(where: { $0.clientRequestID == p.clientRequestID }) { changed = true }
        }
        return changed
    }
    private func valid(_ epoch: UUID) -> Bool { epoch == generation && !Task.isCancelled }
    private struct Pledges: Decodable { let pledges: [Stage1Pledge] }
    private struct Claims: Decodable { let claims: [Stage1Claim]; let nextOffset: Int? }
    private var hillQuery: [URLQueryItem] { hill.map { [.init(name: "hill", value: $0)] } ?? [] }
    private static func page(_ offset: Int) -> [URLQueryItem] { [.init(name: "limit", value: "50"), .init(name: "offset", value: String(offset))] }
    // Claim discovery is bounded server-side at ten per page; continue by nextOffset.
    private static func claimsPage(_ offset: Int) -> [URLQueryItem] { [.init(name: "limit", value: "10"), .init(name: "offset", value: String(offset))] }
    private func pageQuery(_ offset: Int) -> [URLQueryItem] { hillQuery + Self.page(offset) }
    static func path(_ value: String) -> String { value.addingPercentEncoding(withAllowedCharacters: .alphanumerics) ?? "" }

    private func read<T: Decodable>(_ path: String, query: [URLQueryItem] = [], owner: Stage1Owner?) async -> Stage1Load<T> {
        let epoch = generation
        do { return .loaded(try await service.request("GET", path, query: query, body: nil, owner: owner).decode()) }
        catch Stage1Error.disabled { if valid(epoch) { visible = false }; return .unavailable }
        catch Stage1Error.actionsDisabled { if valid(epoch) { actionsEnabled = false }; return .unavailable }
        catch { return .unavailable }
    }
    private static func withoutEligibility(_ lot: Stage1Pledge) -> Stage1Pledge {
        var value = lot
        value.eligibility = nil; value.eligibilityWeek = nil; value.chainTime = nil
        value.withdrawalsPausedUntil = nil
        return value
    }
    func loadLotActions(_ id: String) async {
        guard visible, actionsEnabled, let owner, let lot = pledges.value?.first(where: { $0.id == id }),
              !eligibilityLoading.contains(id) else { return }
        let epoch = generation
        eligibilityLoading.insert(id); eligibilityFailures.remove(id)
        defer { if epoch == generation { eligibilityLoading.remove(id) } }
        do {
            let next = try await Stage1Plans.freshLot(lot, service: service, owner: owner)
            guard valid(epoch), visible, actionsEnabled, var rows = pledges.value,
                  let index = rows.firstIndex(where: { $0.id == id }) else { return }
            rows[index] = next; pledges = .loaded(rows)
        } catch Stage1Error.actionsDisabled { if valid(epoch) { actionsEnabled = false } }
        catch {
            if valid(epoch) { eligibilityFailures.insert(id) }
        }
    }

    func loadMore(_ kind: String) async {
        guard visible, let owner, more.contains(kind), let offset = offsets[kind], !loadingMore.contains(kind) else { return }
        guard !["claims", "lookups"].contains(kind) || actionsEnabled else { return }
        let epoch = generation
        loadingMore.insert(kind); defer { if valid(epoch) { loadingMore.remove(kind) } }
        do {
            let json = try await service.request("GET", "/stage1/me/\(kind)", query: kind == "claims" ? Self.claimsPage(offset) : pageQuery(offset), body: nil, owner: owner)
            guard valid(epoch), visible else { return }
            switch kind {
            case "pay", "dung":
                let page: Stage1Payments = try json.decode()
                guard var old = kind == "pay" ? pay.value : dung.value else { return }
                old.paid += page.paid; old.pending += page.pending
                if kind == "pay" { pay = .loaded(old) } else { dung = .loaded(old) }
                if page.hasMore ?? (max(page.paid.count, page.pending.count) == 50) { offsets[kind] = offset + 50 } else { more.remove(kind) }
            case "pledges":
                let page: Pledges = try json.decode()
                pledges = .loaded((pledges.value ?? []) + page.pledges.map(Self.withoutEligibility))
                if page.pledges.count == 50 { offsets[kind] = offset + 50 } else { more.remove(kind) }
            case "claims":
                let page: Claims = try json.decode()
                claims = .loaded((claims.value ?? []) + page.claims)
                if let next = page.nextOffset, next > offset { offsets[kind] = next } else { more.remove(kind) }
            case "lookups":
                let page: Lookups = try json.decode()
                transports = .loaded((transports.value ?? []) + (try page.tables.map(Self.transport)))
                if let next = page.nextOffset, next > offset { offsets[kind] = next } else { more.remove(kind) }
            default: break
            }
        } catch Stage1Error.disabled { if valid(epoch) { visible = false } }
        catch Stage1Error.actionsDisabled { if valid(epoch) { actionsEnabled = false } }
        catch {
            guard valid(epoch) else { return }
            switch kind { case "pay": pay = .unavailable; case "dung": dung = .unavailable; case "claims": claims = .unavailable; case "pledges": pledges = .unavailable; case "lookups": transports = .unavailable; default: break }
        }
    }

    func loadTransports() async {
        guard let owner, visible, actionsEnabled else { return }
        let epoch = generation
        do {
            let page: Lookups = try await service.request("GET", "/stage1/me/lookups", query: Self.page(0), body: nil, owner: owner).decode()
            guard valid(epoch), self.owner == owner, visible, actionsEnabled else { return }
            transports = .loaded(try page.tables.map(Self.transport))
            if let next = page.nextOffset, next > 0 { more.insert("lookups"); offsets["lookups"] = next }
            else { more.remove("lookups"); offsets.removeValue(forKey: "lookups") }
        } catch Stage1Error.actionsDisabled { if valid(epoch) { actionsEnabled = false } }
        catch { if valid(epoch) { transports = .unavailable } }
    }
    private struct Lookups: Decodable {
        struct Table: Decodable { let address: String; let state: String }
        let tables: [Table]; let nextOffset: Int?
    }
    private static func transport(_ row: Lookups.Table) throws -> Transport {
        _ = try Stage1Address.key(row.address)
        guard ["active", "closeable", "cooling", "missing"].contains(row.state) else { throw Stage1Error.unavailable }
        let mode: Stage1LookupMode? = row.state == "active" ? .deactivate : row.state == "closeable" ? .close : nil
        return .init(id: row.address, plan: mode.map { .init(action: .transport,
            request: ["mode": .string($0.rawValue), "lookupTable": .string(row.address)],
            intent: .claimTransport(mode: $0, table: row.address)) })
    }
}
