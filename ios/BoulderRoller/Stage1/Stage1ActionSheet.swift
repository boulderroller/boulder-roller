import SwiftUI

struct Stage1ActionSheet: View {
    let selection: Stage1Selection
    let registry: Stage1MintRegistry
    @Environment(\.dismiss) private var dismiss
    @State private var model: Stage1TransactionModel
    @State private var amount = ""
    @State private var mint = ""
    @State private var lock: UInt16 = 0
    @State private var preparing = false
    @State private var inputFailed = false
    @State private var inputPaused = false

    init(selection: Stage1Selection, registry: Stage1MintRegistry, owner: Stage1Owner,
         service: any Stage1Servicing, rpc: any Stage1RPCServicing, store: Stage1OperationStore,
         currentOwner: @escaping () -> Stage1Owner?) {
        self.selection = selection; self.registry = registry
        _model = State(initialValue: Stage1TransactionModel(owner: owner, scope: selection.operationScope,
            service: service, rpc: rpc, store: store, currentOwner: currentOwner))
    }
    private var tokens: [Stage1Bonding.Asset] { selection.bonding.map(registry.stakingAssets) ?? [] }
    private var selectedMint: String { mint.isEmpty ? tokens.first?.mint ?? "" : mint }
    private var units: UInt64? { registry.token(selectedMint).flatMap { Stage1Numbers.baseUnits(amount, decimals: $0.decimals) } }
    private var canContinue: Bool { model.canPrepare && !preparing && (selection.action != .pledge || (units ?? 0) > 0) }

    var body: some View {
        ZStack {
            Theme.sheet.ignoresSafeArea()
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    SheetHeader(title: selection.label, doneLabel: "Cancel") { dismiss() }
                        .disabled(model.isWorking || preparing).padding(.top, 6)
                    VStack(alignment: .leading, spacing: 16) {
                        if let name = selection.climbName { Text(name).font(.body).foregroundStyle(Theme.ink) }
                        if selection.action == .registration {
                            GroupCard { Stage1Fact(label: "Wallet", value: model.owner.wallet) }
                        }
                        if model.checked == nil && model.pending == nil && (model.state != .confirmed || (selection.claim != nil && model.lastConfirmedAction == .transport)) {
                            inputs
                            if canContinue || model.isWorking || preparing {
                                CenteredActionRow(label: preparing || model.isWorking ? Stage1Copy.loading : "Continue") {
                                    Task { await prepare() }
                                }.disabled(!canContinue)
                            }
                        }
                        if let checked = model.checked { confirmation(checked.plan) }
                        if let raw = model.pending?.withdrawalsPausedUntil, let until = Stage1Numbers.uint(raw) {
                            TimelineView(.periodic(from: .now, by: 1)) { context in
                                if context.date.timeIntervalSince1970 < Double(until) {
                                    GroupCard { GrammarRow(label: Stage1Copy.withdrawalsPaused) }
                                }
                            }
                        }
                        if let statusLabel {
                            GroupCard { GrammarRow(label: statusLabel) }
                                .accessibilityIdentifier("stage1-operation-state")
                        }
                    }
                    .padding(.horizontal, Theme.margin).padding(.top, 22).padding(.bottom, 32)
                }
            }
        }
        .interactiveDismissDisabled(model.isWorking || preparing)
        .task {
            while !Task.isCancelled {
                await model.reconcile()
                do { try await Task.sleep(for: .seconds(4)) } catch { return }
            }
        }
    }

    @ViewBuilder private var inputs: some View {
        if selection.action == .pledge {
            GroupCard {
                HStack {
                    Text(Stage1Copy.token).font(.body).foregroundStyle(Theme.ink).accessibilityHidden(true)
                    Spacer(minLength: 8)
                    Picker(Stage1Copy.token, selection: Binding(get: { selectedMint }, set: { mint = $0 })) {
                        ForEach(tokens, id: \.mint) { asset in
                            Text(registry.token(asset.mint)?.symbol ?? Stage1Copy.unknownMint).tag(asset.mint)
                        }
                    }
                }.padding(14)
                RowSeparator()
                TextField(Stage1Copy.amount, text: $amount)
                    .keyboardType(.decimalPad).font(.numeral(.largeTitle)).monospacedDigit()
                    .padding(16).accessibilityLabel(Stage1Copy.amount)
            }
        }
        if selection.action == .pledge || selection.action == .convert {
            GroupCard {
                HStack {
                    Text(Stage1Copy.lock).font(.body).foregroundStyle(Theme.ink).accessibilityHidden(true)
                    Spacer(minLength: 8)
                    Picker(Stage1Copy.lock, selection: $lock) {
                        ForEach(Stage1Plans.locks, id: \.self) { n in Text(Format.number(Double(n), places: 0)).tag(n) }
                    }
                }.padding(14)
            }
        }
    }

    private func confirmation(_ plan: Stage1Plan) -> some View {
        VStack(alignment: .leading, spacing: 16) {
            GroupCard {
                GrammarRow(label: Stage1Copy.confirmation)
                if let amount = confirmationAmount(plan) { Stage1Fact(label: Stage1Copy.amount, value: amount) }
                switch plan.intent {
                case let .pledge(_, _, _, _, _, weeks, bonded, _):
                    if !bonded { Stage1Fact(label: Stage1Copy.foundingLock, value: Format.number(26.0, places: 0)) }
                    Stage1Fact(label: Stage1Copy.lock, value: Format.number(Double(weeks), places: 0))
                case let .convertPledge(_, _, _, weeks, _):
                    Stage1Fact(label: Stage1Copy.lock, value: Format.number(Double(weeks), places: 0))
                case .withdrawalNotice, .beginWithdrawal, .completeWithdrawal:
                    if let basis = selection.withdrawal?.data.basisLamports ?? selection.lot?.basisLamports,
                       Stage1Numbers.uint(basis) != nil { Stage1Fact(label: Stage1Copy.basis, value: Format.baseUnits(basis, decimals: 9) + " SOL") }
                case let .claimTransport(_, table, _, _): Stage1Fact(label: Stage1Copy.transport, value: table)
                default: EmptyView()
                }
            }
            HoldCapsule(label: [Stage1Copy.hold, confirmationAmount(plan)].compactMap { $0 }.joined(separator: " "),
                tint: plan.action == .pledge ? Theme.blue : Theme.gray2, enabled: !model.isWorking && model.pending == nil) {
                    Task { await model.commit(claimID: selection.claim?.id) }
                }
                .accessibilityIdentifier("stage1-hold")
        }
    }
    private func confirmationAmount(_ plan: Stage1Plan) -> String? {
        switch plan.intent {
        case let .pledge(_, _, mint, _, amount, _, _, _): return registry.amount(String(amount), mint: mint)
        case let .cashClaim(mint, leaves, _): return leaves.first.flatMap { registry.amount(String($0.leaf.amount), mint: mint) }
        case let .dungClaim(leaves, _): return leaves.first.flatMap { registry.amount(String($0.leaf.amount), mint: Stage1MintRegistry.dung) }
        case .cancelPledge, .convertPledge: return selection.lot.flatMap { registry.amount($0.units, mint: $0.mint) }
        default: return nil
        }
    }
    private var statusLabel: String? {
        if inputPaused { return Stage1Copy.withdrawalsPaused }
        if inputFailed { return Stage1Copy.unavailable }
        switch model.state {
        case .idle, .checked: return nil
        case .working: return Stage1Copy.loading
        case .pending: return "Pending"
        case .delayed: return "Delayed"
        case .needsReview: return "Needs review"
        case .confirmed: return "Confirmed"
        case .unavailable: return Stage1Copy.unavailable
        case .withdrawalsPaused: return Stage1Copy.withdrawalsPaused
        }
    }
    private func prepare() async {
        guard canContinue else { return }
        preparing = true; inputFailed = false; inputPaused = false
        defer { preparing = false }
        do {
            let plan: Stage1Plan
            if let supplied = selection.plan { plan = supplied }
            else if let r = selection.registration { plan = try Stage1Plans.registration(r) }
            else if let b = selection.bonding, let units {
                plan = try Stage1Plans.pledge(b, registry: registry, mint: selectedMint, amount: units, lock: lock, depositID: .random(in: .min ... .max))
            } else if let claim = selection.claim {
                var table = model.store.claimLookup(model.owner, claim: claim.id)
                if let address = table {
                    guard let lookup = try await model.rpc.lookup(address), lookup.authority == model.owner.wallet else { throw Stage1Error.unavailable }
                    if !lookup.active { model.store.clearLookup(model.owner, table: address); table = nil }
                }
                plan = claim.requiresLookup && table == nil
                    ? try await Stage1Plans.transport(claim, wallet: model.owner.wallet, slot: model.rpc.slot())
                    : try Stage1Plans.claim(claim, lookup: table)
            } else if let lot = selection.lot {
                let fresh = try await Stage1Plans.freshLot(lot, service: model.service, owner: model.owner)
                plan = try Stage1Plans.lot(fresh, action: selection.action, lock: lock, requestID: .random(in: .min ... .max), withdrawal: selection.withdrawal)
            } else { throw Stage1Error.unavailable }
            await model.prepare(plan)
        } catch Stage1Error.withdrawalsPaused { inputPaused = true }
        catch { inputFailed = true }
    }
}
