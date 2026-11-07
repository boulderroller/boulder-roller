import CryptoKit
import Foundation

@MainActor
protocol Stage1Servicing {
    func status() async throws -> Stage1Status
    func request(_ method: String, _ path: String, query: [URLQueryItem], body: [String: Stage1JSON]?, owner: Stage1Owner?) async throws -> Stage1JSON
    func sign(_ transaction: String, owner: Stage1Owner, intent: Stage1TransactionIntent,
              tables: [SolanaTransaction.ResolvedLookupTable], testPool: Stage1TestPool?) async throws -> String
}

@MainActor
struct LiveStage1Service: Stage1Servicing {
    func status() async throws -> Stage1Status { try await APIClient.shared.stage1Status() }
    func request(_ method: String, _ path: String, query: [URLQueryItem] = [], body: [String: Stage1JSON]? = nil,
                 owner: Stage1Owner?) async throws -> Stage1JSON {
        try await APIClient.shared.stage1Request(method, path, query: query, body: body, owner: owner)
    }
    func sign(_ transaction: String, owner: Stage1Owner, intent: Stage1TransactionIntent,
              tables: [SolanaTransaction.ResolvedLookupTable], testPool: Stage1TestPool?) async throws -> String {
        try await TransactionSigner.sign(transactionB64: transaction, wallet: owner.wallet,
            intent: .stage1(intent, wallet: owner.wallet), lookupTables: tables, stage1TestPool: testPool)
    }
}

/// Identity validated against the program's canonical finalized test-pool
/// account and its SPL mint. Neither prepare JSON nor /mints is signing trust.
struct Stage1TestPool: Equatable {
    let provider: String
    let mint: String
}

struct Stage1Lookup {
    let address: String
    let authority: String
    let deactivationSlot: UInt64
    let lastExtendedSlot: UInt64
    let contextSlot: UInt64
    let addresses: [Data]
    var active: Bool { deactivationSlot == UInt64.max }
    func resolved(owner: String) throws -> SolanaTransaction.ResolvedLookupTable {
        guard authority == owner, active, lastExtendedSlot < contextSlot else { throw Stage1Error.unavailable }
        return .init(address: try Stage1Address.key(address), authority: try Stage1Address.key(owner), active: true, addresses: addresses)
    }
}

enum Stage1Receipt { case pending, confirmed, failed }
@MainActor
protocol Stage1RPCServicing {
    func slot() async throws -> UInt64
    func lookup(_ address: String) async throws -> Stage1Lookup?
    func testPool() async throws -> Stage1TestPool
    func settlement(signature: String, blockhash: String) async throws -> Stage1Receipt
}

/// Read-only RPC transport. There is deliberately no transaction-send method.
@MainActor
struct Stage1RPC: Stage1RPCServicing {
    private let url: URL
    private let session: URLSession
    init(url: URL = AppConfig.solanaRPCURL, session: URLSession = .shared) {
        self.url = url; self.session = session
    }
    private func call<T: Decodable>(_ method: String, _ params: [Stage1JSON]) async throws -> T {
        var request = URLRequest(url: url)
        request.httpMethod = "POST"; request.timeoutInterval = 25
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(Stage1JSON.object([
            "jsonrpc": .string("2.0"), "id": .number(1), "method": .string(method), "params": .array(params)]))
        let (data, response) = try await session.data(for: request)
        guard let response = response as? HTTPURLResponse, (200..<300).contains(response.statusCode) else { throw Stage1Error.unavailable }
        return try JSONDecoder().decode(RPCResult<T>.self, from: data).result
    }
    private struct RPCResult<T: Decodable>: Decodable { let result: T }
    struct Context: Decodable { let slot: UInt64 }
    struct Account: Decodable { let owner: String; let executable: Bool; let data: [String] }
    struct AccountRead: Decodable { let context: Context; let value: Account? }
    private func account(_ address: String) async throws -> AccountRead {
        try await call("getAccountInfo", [.string(address), .object(["encoding": .string("base64"), "commitment": .string("finalized")])])
    }
    func slot() async throws -> UInt64 { try await call("getSlot", [.object(["commitment": .string("finalized")])]) }
    func lookup(_ address: String) async throws -> Stage1Lookup? {
        try Self.decodeLookup(address, read: await account(address))
    }
    static func decodeLookup(_ address: String, read: AccountRead) throws -> Stage1Lookup? {
        guard let account = read.value else { return nil }
        guard account.owner == Stage1Address.lookupProgram, !account.executable, account.data.count == 2,
              account.data[1] == "base64", let data = Data(base64Encoded: account.data[0]),
              data.count >= 56, (data.count - 56).isMultiple(of: 32), data.count <= 56 + 256 * 32,
              data[0..<4] == Data([1,0,0,0]), data[21] == 1 else { throw Stage1Error.unavailable }
        func u64(_ offset: Int) -> UInt64 { data[offset..<offset+8].enumerated().reduce(0) { $0 | UInt64($1.element) << ($1.offset * 8) } }
        return .init(address: address, authority: Base58.encode(data.subdata(in: 22..<54)), deactivationSlot: u64(4),
            lastExtendedSlot: u64(12), contextSlot: read.context.slot,
            addresses: stride(from: 56, to: data.count, by: 32).map { data.subdata(in: $0..<$0+32) })
    }
    func testPool() async throws -> Stage1TestPool {
        let address = Base58.encode(try Stage1Address.pda("s1v1_test_pool"))
        let read = try await account(address)
        let identity = try Self.decodeTestPool(read)
        let mintRead = try await account(identity.mint)
        guard let mint = mintRead.value, mint.owner == BalanceTransactionFirewall.tokenProgram, !mint.executable,
              mint.data.count == 2, mint.data[1] == "base64", let data = Data(base64Encoded: mint.data[0]),
              data.count == 82, data[44] == 9, data[45] == 1 else { throw Stage1Error.unavailable }
        return identity
    }
    static func decodeTestPool(_ read: AccountRead) throws -> Stage1TestPool {
        guard let account = read.value, account.owner == BalanceTransactionFirewall.boulderProgram, !account.executable,
              account.data.count == 2, account.data[1] == "base64", let data = Data(base64Encoded: account.data[0]),
              data.count == 74, data[0..<8] == Data(SHA256.hash(data: Data("account:Stage1TestPool".utf8))).prefix(8),
              data[8] == 1 else { throw Stage1Error.unavailable }
        return .init(provider: Base58.encode(data.subdata(in: 9..<41)), mint: Base58.encode(data.subdata(in: 41..<73)))
    }
    func settlement(signature: String, blockhash: String) async throws -> Stage1Receipt {
        struct SignatureStatus: Decodable { let confirmationStatus: String?; let err: Stage1JSON? }
        struct Statuses: Decodable { let value: [SignatureStatus?] }
        struct Valid: Decodable { let value: Bool }
        func read() async throws -> SignatureStatus? {
            let result: Statuses = try await call("getSignatureStatuses", [.array([.string(signature)]), .object(["searchTransactionHistory": .bool(true)])])
            guard result.value.count == 1 else { throw Stage1Error.unavailable }; return result.value[0]
        }
        func result(_ status: SignatureStatus) -> Stage1Receipt {
            guard status.confirmationStatus == "finalized" else { return .pending }
            return status.err == nil || status.err == .null ? .confirmed : .failed
        }
        if let status = try await read() { return result(status) }
        for commitment in ["finalized", "confirmed"] {
            let valid: Valid = try await call("isBlockhashValid", [.string(blockhash), .object(["commitment": .string(commitment)])])
            if valid.value { return .pending }
        }
        return try await read().map(result) ?? .failed
    }
}
