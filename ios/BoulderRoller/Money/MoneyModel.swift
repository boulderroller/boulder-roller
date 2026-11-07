import Foundation
import Observation

enum BalanceSourceError: LocalizedError {
    case unavailable(String)

    var errorDescription: String? {
        switch self {
        case let .unavailable(source):
            return "\(source) is unavailable"
        }
    }
}

struct BalanceSubmissionSnapshot: Equatable {
    let operationId: String?
    let projectionStatus: String?
    let confirmationStatus: String?
    let riderState: String?
}

/// Display projection for wire amounts. Missing, malformed, NaN, and infinite
/// values remain unavailable instead of reaching Format.amount's legacy zero
/// fallback.
struct FiniteMoneyAmount: Equatable {
    let value: Double?

    init(_ raw: String?) {
        guard let raw,
              let parsed = Double(raw),
              parsed.isFinite
        else {
            value = nil
            return
        }
        value = parsed
    }

    var isAvailable: Bool { value != nil }

    var display: String {
        value.map { Format.amount($0) } ?? "—"
    }

    var calDisplay: String {
        value.map { "\(Format.amount($0)) CAL" } ?? "—"
    }
}

/// Production-used Balance network/signing boundary. Tests replace this one
/// seam; the app implementation continues to call the real API and signer.
@MainActor
protocol MoneyServicing: AnyObject {
    func prepareStake(vaultId: Int, calAmount: Int) async throws -> PreparedVaultTransaction
    func submitStake(
        vaultId: Int,
        calAmount: Int,
        signedTransaction: String,
        lastValidBlockHeight: Int,
        clientRequestId: String
    ) async throws -> BalanceSubmissionSnapshot
    func prepareUnstake(
        vaultId: Int,
        lpAmountBaseUnits: String?
    ) async throws -> PreparedVaultTransaction
    func submitUnstake(
        vaultId: Int,
        lpAmountBaseUnits: String?,
        signedTransaction: String,
        lastValidBlockHeight: Int,
        clientRequestId: String
    ) async throws -> BalanceSubmissionSnapshot
    func collectHarvest(vaultId: Int, clientRequestId: String) async throws -> BalanceSubmissionSnapshot
    func sign(transaction: String, wallet: String, intent: BalanceTransactionIntent) async throws -> String
    func operationStatus(operationId: String) async throws -> BalanceOperationStatusResponse?
    func operationStatus(
        clientRequestId: String,
        referenceType: String,
        referenceId: String,
        actionType: String
    ) async throws -> BalanceOperationStatusResponse?
    func myStakes() async throws -> [VaultStake]
    func pendingRewards(vaultId: Int) async throws -> Decimal
    func resolveLegacyVaultId(signature: String) async throws -> Int
}

@MainActor
final class LiveMoneyService: MoneyServicing {
    /// `.cacheOnly` hydrates a room from the last successful reads; a miss
    /// anywhere in the chain is an honest "not yet", never a skipped position.
    let policy: CachePolicy

    init(policy: CachePolicy = .network) {
        self.policy = policy
    }

    func prepareStake(vaultId: Int, calAmount: Int) async throws -> PreparedVaultTransaction {
        try await APIClient.shared.prepareStake(vaultId: vaultId, calAmount: calAmount)
    }

    func submitStake(
        vaultId: Int,
        calAmount: Int,
        signedTransaction: String,
        lastValidBlockHeight: Int,
        clientRequestId: String
    ) async throws -> BalanceSubmissionSnapshot {
        let response = try await APIClient.shared.submitStake(
            vaultId: vaultId,
            calAmount: calAmount,
            signedTransaction: signedTransaction,
            lastValidBlockHeight: lastValidBlockHeight,
            clientRequestId: clientRequestId
        )
        return BalanceSubmissionSnapshot(
            operationId: response.operationId,
            projectionStatus: response.projectionStatus,
            confirmationStatus: response.confirmationStatus,
            riderState: response.riderState
        )
    }

    func prepareUnstake(
        vaultId: Int,
        lpAmountBaseUnits: String?
    ) async throws -> PreparedVaultTransaction {
        try await APIClient.shared.prepareUnstake(
            vaultId: vaultId,
            lpAmountBaseUnits: lpAmountBaseUnits
        )
    }

    func submitUnstake(
        vaultId: Int,
        lpAmountBaseUnits: String?,
        signedTransaction: String,
        lastValidBlockHeight: Int,
        clientRequestId: String
    ) async throws -> BalanceSubmissionSnapshot {
        let response = try await APIClient.shared.submitUnstake(
            vaultId: vaultId,
            lpAmountBaseUnits: lpAmountBaseUnits,
            signedTransaction: signedTransaction,
            lastValidBlockHeight: lastValidBlockHeight,
            clientRequestId: clientRequestId
        )
        return BalanceSubmissionSnapshot(
            operationId: response.operationId,
            projectionStatus: response.projectionStatus,
            confirmationStatus: response.confirmationStatus,
            riderState: response.riderState
        )
    }

    func collectHarvest(vaultId: Int, clientRequestId: String) async throws -> BalanceSubmissionSnapshot {
        let response = try await APIClient.shared.collectHarvest(
            vaultId: vaultId, clientRequestId: clientRequestId
        )
        return BalanceSubmissionSnapshot(
            operationId: response.operationId,
            projectionStatus: response.projectionStatus,
            confirmationStatus: response.confirmationStatus,
            riderState: response.riderState
        )
    }

    func sign(transaction: String, wallet: String, intent: BalanceTransactionIntent) async throws -> String {
        try await TransactionSigner.sign(transactionB64: transaction, wallet: wallet, intent: intent)
    }

    func operationStatus(operationId: String) async throws -> BalanceOperationStatusResponse? {
        try await APIClient.shared.balanceOperation(operationId: operationId)
    }

    func operationStatus(
        clientRequestId: String,
        referenceType: String,
        referenceId: String,
        actionType: String
    ) async throws -> BalanceOperationStatusResponse? {
        try await APIClient.shared.balanceOperation(
            clientRequestId: clientRequestId,
            referenceType: referenceType,
            referenceId: referenceId,
            actionType: actionType
        )
    }

    func myStakes() async throws -> [VaultStake] {
        guard let stakes = try await APIClient.shared.myStakes(policy: policy).stakes else {
            throw BalanceSourceError.unavailable("Positions")
        }
        return stakes
    }

    func pendingRewards(vaultId: Int) async throws -> Decimal {
        let response = try await APIClient.shared.pendingRewards(vaultId: vaultId, policy: policy)
        guard let raw = response.totalPending, let value = Decimal(string: raw) else {
            throw BalanceSourceError.unavailable("Pending DUNG")
        }
        return value
    }

    func resolveLegacyVaultId(signature: String) async throws -> Int {
        if policy == .cacheOnly {
            guard let hit = VaultDirectory.cachedVaultId(forSignature: signature) else {
                throw CacheMiss()
            }
            return hit
        }
        return try await VaultDirectory.vaultId(forSignature: signature)
    }
}

/// Signature-to-id fallback for pre-v1.1 position rows. A failed or incomplete
/// directory read remains unavailable; it never becomes a skipped position.
@MainActor
enum VaultDirectory {
    private static var cache: [String: VaultSummary] = [:]
    private static var loaded = false

    /// Memory-only lookup for cached-first hydrates — never loads.
    static func cachedVaultId(forSignature signature: String) -> Int? {
        cache[signature]?.id
    }

    static func vaultId(forSignature signature: String) async throws -> Int {
        if let hit = cache[signature] { return hit.id }
        if !loaded { try await loadAll() }
        guard let hit = cache[signature] else {
            throw BalanceSourceError.unavailable("Vault identity")
        }
        return hit.id
    }

    private static func loadAll() async throws {
        var offset = 0
        var rowsBySignature: [String: VaultSummary] = [:]
        while true {
            let page = try await APIClient.shared.vaults(limit: 100, offset: offset)
            guard let rows = page.vaults else {
                throw BalanceSourceError.unavailable("Vault directory")
            }
            for row in rows { rowsBySignature[row.signatureHex] = row }
            if rows.count < 100 {
                cache = rowsBySignature
                loaded = true
                return
            }
            offset += rows.count
        }
    }
}

protocol BalanceReconciliationClock {
    var now: TimeInterval { get }
    func sleep(seconds: TimeInterval) async
}

struct LiveBalanceReconciliationClock: BalanceReconciliationClock {
    var now: TimeInterval { ProcessInfo.processInfo.systemUptime }

    func sleep(seconds: TimeInterval) async {
        let nanoseconds = UInt64(max(seconds, 0) * 1_000_000_000)
        try? await Task.sleep(nanoseconds: nanoseconds)
    }
}

/// Rider-control availability projected from the server's ordered rollout.
/// Missing, blocked, or non-prefix status never creates a live control.
struct BalanceActionAvailability: Equatable {
    let collect: Bool
    let deposit: Bool
    let withdraw: Bool

    static let unavailable = BalanceActionAvailability(
        collect: false,
        deposit: false,
        withdraw: false
    )

    init(status: SystemStatusResponse?) {
        guard let rollout = status?.balanceRollout,
              rollout.enforced,
              rollout.orderValid,
              rollout.blockers.isEmpty,
              rollout.enabledActions.count <= rollout.actionOrder.count,
              Array(rollout.actionOrder.prefix(rollout.enabledActions.count))
                == rollout.enabledActions
        else {
            self = .unavailable
            return
        }
        let enabled = Set(rollout.enabledActions)
        collect = enabled.contains("collect_dung")
        deposit = enabled.contains("deposit_cal")
        withdraw = enabled.contains("withdraw_cal")
    }

    private init(collect: Bool, deposit: Bool, withdraw: Bool) {
        self.collect = collect
        self.deposit = deposit
        self.withdraw = withdraw
    }
}

/// Truth-preserving aggregate used by both the avatar and Settlements.
/// A single unavailable identity or pending-rewards read makes the aggregate
/// unavailable; it cannot be represented as zero or a partial sum.
@MainActor
enum SettlementTruth {
    static func uncollectedTotal(policy: CachePolicy = .network) async -> Decimal? {
        await uncollectedTotal(service: LiveMoneyService(policy: policy))
    }

    static func uncollectedTotal(service: any MoneyServicing) async -> Decimal? {
        do {
            let stakes = try await service.myStakes()
            var total = Decimal.zero
            for stake in stakes {
                let vaultId: Int
                if let deployedId = stake.vaultId {
                    vaultId = deployedId
                } else {
                    vaultId = try await service.resolveLegacyVaultId(
                        signature: stake.vaultSignature
                    )
                }
                total += try await service.pendingRewards(vaultId: vaultId)
            }
            return total
        } catch {
            return nil
        }
    }
}

/// One successfully resolved vault-position read. A nil stake here means the
/// complete v1.1 plus legacy set proved that the rider has no position.
struct ResolvedVaultPosition {
    let stake: VaultStake?
    let depositPriorCalBaseUnits: String

    var withdrawPositionCal: Double? {
        guard let stake,
              let humanRaw = stake.calStaked,
              let human = Double(humanRaw),
              human.isFinite,
              human > 0,
              let humanDecimal = Decimal(
                string: humanRaw,
                locale: Locale(identifier: "en_US_POSIX")
              ),
              let calRaw = stake.calStakedBaseUnits,
              let calBase = UInt128(calRaw),
              calBase > 0,
              let calDecimal = Decimal(
                string: calRaw,
                locale: Locale(identifier: "en_US_POSIX")
              ),
              humanDecimal * Decimal(1_000_000_000) == calDecimal,
              let lpRaw = stake.lpTokensBaseUnits,
              let lpBase = UInt128(lpRaw),
              lpBase > 0
        else { return nil }
        return human
    }
}

/// Resolves every legacy row before declaring that the current vault has no
/// position. Any missing identity or duplicate match keeps the baseline
/// unavailable instead of manufacturing prior zero.
@MainActor
enum VaultPositionTruthResolver {
    static func resolve(
        stakes: [VaultStake],
        vaultId: Int,
        resolveLegacy: (String) async throws -> Int
    ) async throws -> ResolvedVaultPosition {
        var matches = stakes.filter { $0.vaultId == vaultId }
        for stake in stakes where stake.vaultId == nil {
            let resolvedId = try await resolveLegacy(stake.vaultSignature)
            if resolvedId == vaultId { matches.append(stake) }
        }
        guard matches.count <= 1 else {
            throw BalanceSourceError.unavailable("Position identity")
        }
        guard let stake = matches.first else {
            return ResolvedVaultPosition(stake: nil, depositPriorCalBaseUnits: "0")
        }
        guard let raw = stake.calStakedBaseUnits,
              UInt128(raw) != nil
        else {
            throw BalanceSourceError.unavailable("Position amount")
        }
        return ResolvedVaultPosition(stake: stake, depositPriorCalBaseUnits: raw)
    }
}

/// The money room's engine: deposit, composed withdraw, and Collect DUNG.
/// The injectable seam above is used directly by production and deterministic
/// tests; no parallel replica grades the state machine.
@MainActor
@Observable
final class MoneyModel {
    enum ActionResult: Equatable {
        case deposited
        case withdrawn
        case collected
    }

    enum Status: Equatable {
        case idle
        case working
        case pending
        case delayed
        case needsReview
        case done(ActionResult)
        case failed(String)
    }

    private enum Action {
        case deposit(vaultId: Int, priorCalBaseUnits: String)
        case withdraw(vaultId: Int, priorLpBaseUnits: String)
        case collect(vaultId: Int)

        var vaultId: Int {
            switch self {
            case let .deposit(vaultId, _): return vaultId
            case let .withdraw(vaultId, _): return vaultId
            case let .collect(vaultId): return vaultId
            }
        }

        var actionType: String {
            switch self {
            case .deposit: return "deposit_cal"
            case .withdraw: return "withdraw_cal"
            case .collect: return "collect_dung"
            }
        }

        var result: ActionResult {
            switch self {
            case .deposit: return .deposited
            case .withdraw: return .withdrawn
            case .collect: return .collected
            }
        }
    }

    private enum RereadResult {
        case confirmed
        case notYetVisible
        case unavailable
    }

    private(set) var status: Status = .idle
    private(set) var supportRequestId: String?
    private(set) var supportOperationId: String?

    private let service: any MoneyServicing
    private let clock: any BalanceReconciliationClock
    private let timeout: TimeInterval
    private let pollInterval: TimeInterval
    private let makeRequestId: (String) -> String

    init() {
        self.service = LiveMoneyService()
        self.clock = LiveBalanceReconciliationClock()
        self.timeout = 20
        self.pollInterval = 1
        self.makeRequestId = { prefix in
            "\(prefix)-\(UUID().uuidString.lowercased())"
        }
    }

    #if DEBUG
    /// Render-evidence initializer. The DEBUG-only harness presents the real
    /// sheet state without preparing, signing, submitting, or polling.
    init(renderStatus: Status) {
        self.service = LiveMoneyService()
        self.clock = LiveBalanceReconciliationClock()
        self.timeout = 20
        self.pollInterval = 1
        self.makeRequestId = { prefix in
            "\(prefix)-\(UUID().uuidString.lowercased())"
        }
        self.status = renderStatus
    }
    #endif

    init(
        service: any MoneyServicing,
        clock: any BalanceReconciliationClock,
        timeout: TimeInterval = 20,
        pollInterval: TimeInterval = 1,
        makeRequestId: @escaping (String) -> String
    ) {
        self.service = service
        self.clock = clock
        self.timeout = timeout
        self.pollInterval = pollInterval
        self.makeRequestId = makeRequestId
    }

    var isWorking: Bool { status == .working || status == .pending }

    var canSubmit: Bool {
        if case .idle = status { return true }
        if case .failed = status { return true }
        return false
    }

    func reset() {
        status = .idle
        supportRequestId = nil
        supportOperationId = nil
    }

    // MARK: Deposit (stake CAL)

    func deposit(
        vaultId: Int,
        amount: Int,
        priorCalBaseUnits: String,
        wallet: String
    ) async {
        status = .working
        let requestId = makeRequestId("deposit")
        supportRequestId = requestId

        guard let wholeCAL = UInt64(exactly: amount) else {
            status = .failed("Invalid CAL amount")
            return
        }
        let (amountBaseUnits, overflow) = wholeCAL.multipliedReportingOverflow(
            by: 1_000_000_000
        )
        guard !overflow, amountBaseUnits > 0 else {
            status = .failed("Invalid CAL amount")
            return
        }

        let prepared: PreparedVaultTransaction
        let signed: String
        do {
            prepared = try await service.prepareStake(vaultId: vaultId, calAmount: amount)
            signed = try await service.sign(
                transaction: prepared.transaction,
                wallet: wallet,
                intent: .stake(
                    vaultId: vaultId,
                    amountBaseUnits: amountBaseUnits,
                    wallet: wallet
                )
            )
        } catch {
            status = .failed(error.localizedDescription)
            return
        }

        do {
            let submitted = try await service.submitStake(
                vaultId: vaultId,
                calAmount: amount,
                signedTransaction: signed,
                lastValidBlockHeight: prepared.lastValidBlockHeight,
                clientRequestId: requestId
            )
            supportOperationId = submitted.operationId
            status = .pending
            await reconcile(
                submitted: submitted,
                requestId: requestId,
                action: .deposit(
                    vaultId: vaultId,
                    priorCalBaseUnits: priorCalBaseUnits
                )
            )
        } catch {
            // Once a signed payload has been submitted, transport and auth
            // failures are ambiguous. Reconcile the same client request.
            status = .pending
            await reconcile(
                submitted: nil,
                requestId: requestId,
                action: .deposit(
                    vaultId: vaultId,
                    priorCalBaseUnits: priorCalBaseUnits
                )
            )
        }
    }

    // MARK: Withdraw (backend-composed collect-before-unstake)

    func withdraw(
        vaultId: Int,
        lpAmountBaseUnits: String?,
        priorLpAmountBaseUnits: String,
        wallet: String
    ) async {
        status = .working
        let requestId = makeRequestId("withdraw")
        supportRequestId = requestId

        let prepared: PreparedVaultTransaction
        let signed: String
        do {
            prepared = try await service.prepareUnstake(
                vaultId: vaultId,
                lpAmountBaseUnits: lpAmountBaseUnits
            )
            let exactLP = lpAmountBaseUnits ?? priorLpAmountBaseUnits
            guard let amountBaseUnits = UInt64(exactLP), amountBaseUnits > 0 else {
                status = .failed("Invalid LP amount")
                return
            }
            signed = try await service.sign(
                transaction: prepared.transaction,
                wallet: wallet,
                intent: .unstake(
                    vaultId: vaultId,
                    amountBaseUnits: amountBaseUnits,
                    wallet: wallet
                )
            )
        } catch {
            status = .failed(error.localizedDescription)
            return
        }

        do {
            let submitted = try await service.submitUnstake(
                vaultId: vaultId,
                lpAmountBaseUnits: lpAmountBaseUnits,
                signedTransaction: signed,
                lastValidBlockHeight: prepared.lastValidBlockHeight,
                clientRequestId: requestId
            )
            supportOperationId = submitted.operationId
            status = .pending
            await reconcile(
                submitted: submitted,
                requestId: requestId,
                action: .withdraw(
                    vaultId: vaultId,
                    priorLpBaseUnits: priorLpAmountBaseUnits
                )
            )
        } catch {
            status = .pending
            await reconcile(
                submitted: nil,
                requestId: requestId,
                action: .withdraw(
                    vaultId: vaultId,
                    priorLpBaseUnits: priorLpAmountBaseUnits
                )
            )
        }
    }

    // MARK: Collect DUNG

    func collect(vaultId: Int, wallet _: String) async {
        status = .working
        _ = await harvest(vaultId: vaultId)
    }

    func collectAll(wallet _: String) async {
        status = .working
        do {
            let stakes = try await service.myStakes()
            var targets: [Int] = []
            for stake in stakes {
                let vaultId = try await resolvedVaultId(for: stake)
                let pending = try await service.pendingRewards(vaultId: vaultId)
                if pending > 0 { targets.append(vaultId) }
            }

            // All sources are proven available before the first write. Once a
            // collect is submitted, each operation still reconciles alone.
            var finalizedAny = false
            for vaultId in targets {
                status = .working
                guard await harvest(vaultId: vaultId) else {
                    if finalizedAny { status = .needsReview }
                    return
                }
                finalizedAny = true
            }
            status = .done(.collected)
        } catch {
            status = .needsReview
        }
    }

    @discardableResult
    private func harvest(vaultId: Int) async -> Bool {
        let requestId = makeRequestId("collect")
        supportRequestId = requestId

        do {
            let submitted = try await service.collectHarvest(vaultId: vaultId, clientRequestId: requestId)
            supportOperationId = submitted.operationId
            status = .pending
            return await reconcile(
                submitted: submitted,
                requestId: requestId,
                action: .collect(vaultId: vaultId)
            )
        } catch {
            status = .pending
            return await reconcile(
                submitted: nil,
                requestId: requestId,
                action: .collect(vaultId: vaultId)
            )
        }
    }

    @discardableResult
    private func reconcile(
        submitted: BalanceSubmissionSnapshot?,
        requestId: String,
        action: Action
    ) async -> Bool {
        var operationId = submitted?.operationId
        let deadline = clock.now + timeout

        while true {
            guard !Task.isCancelled else {
                status = .needsReview
                return false
            }

            let operation: BalanceOperationStatusResponse?
            do {
                if let operationId {
                    operation = try await service.operationStatus(operationId: operationId)
                } else {
                    operation = try await service.operationStatus(
                        clientRequestId: requestId,
                        referenceType: "vault",
                        referenceId: String(action.vaultId),
                        actionType: action.actionType
                    )
                }
            } catch {
                status = .needsReview
                return false
            }

            guard !Task.isCancelled else {
                status = .needsReview
                return false
            }

            guard let operation else {
                status = .needsReview
                return false
            }
            operationId = operation.operationId
            supportOperationId = operation.operationId

            guard operation.actionType == action.actionType,
                  operation.referenceType == "vault",
                  operation.referenceId == String(action.vaultId)
            else {
                status = .needsReview
                return false
            }

            if operation.needsReview || operation.readState == "needs_review" {
                status = .needsReview
                return false
            }
            if operation.delayed || operation.readState == "delayed" {
                status = .delayed
                return false
            }
            if operation.recorded && operation.readState == "recorded" {
                let reread = await actionReread(action)
                guard !Task.isCancelled else {
                    status = .needsReview
                    return false
                }
                switch reread {
                case .confirmed:
                    status = .done(action.result)
                    return true
                case .unavailable:
                    status = .needsReview
                    return false
                case .notYetVisible:
                    break
                }
            } else if !(operation.pending && operation.readState == "pending") {
                status = .needsReview
                return false
            }

            if clock.now >= deadline {
                status = .delayed
                return false
            }
            status = .pending
            let remaining = max(deadline - clock.now, 0)
            await clock.sleep(seconds: min(max(pollInterval, 0.05), remaining))
        }
    }

    private func actionReread(_ action: Action) async -> RereadResult {
        do {
            switch action {
            case let .deposit(vaultId, priorCalBaseUnits):
                let stakes = try await service.myStakes()
                guard let current = try await stake(in: stakes, vaultId: vaultId) else {
                    return .notYetVisible
                }
                guard let currentBaseUnits = decimal(current.calStakedBaseUnits) else {
                    return .unavailable
                }
                guard let prior = decimal(priorCalBaseUnits) else { return .unavailable }
                return currentBaseUnits > prior ? .confirmed : .notYetVisible

            case let .withdraw(vaultId, priorLpBaseUnits):
                let stakes = try await service.myStakes()
                guard let current = try await stake(in: stakes, vaultId: vaultId) else {
                    return .confirmed
                }
                guard let currentBaseUnits = decimal(current.lpTokensBaseUnits),
                      let prior = decimal(priorLpBaseUnits)
                else { return .unavailable }
                return currentBaseUnits < prior ? .confirmed : .notYetVisible

            case let .collect(vaultId):
                let pending = try await service.pendingRewards(vaultId: vaultId)
                return pending == 0 ? .confirmed : .notYetVisible
            }
        } catch {
            return .unavailable
        }
    }

    private func stake(in stakes: [VaultStake], vaultId: Int) async throws -> VaultStake? {
        let resolved = try await VaultPositionTruthResolver.resolve(
            stakes: stakes,
            vaultId: vaultId,
            resolveLegacy: { signature in
                try await self.service.resolveLegacyVaultId(signature: signature)
            }
        )
        return resolved.stake
    }

    private func resolvedVaultId(for stake: VaultStake) async throws -> Int {
        if let deployedId = stake.vaultId { return deployedId }
        return try await service.resolveLegacyVaultId(signature: stake.vaultSignature)
    }

    private func decimal(_ value: String?) -> Decimal? {
        guard let value else { return nil }
        return Decimal(string: value, locale: Locale(identifier: "en_US_POSIX"))
    }
}
