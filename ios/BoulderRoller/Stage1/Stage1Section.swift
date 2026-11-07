import SwiftUI

struct Stage1Selection: Identifiable {
    let id = UUID()
    var action: Stage1Action
    var climbName: String?
    var registration: Stage1Registration?
    var bonding: Stage1Bonding?
    var lot: Stage1Pledge?
    var withdrawal: Stage1Withdrawal?
    var claim: Stage1Claim?
    var plan: Stage1Plan?
    var operationScope: Stage1OperationScope {
        var record = lot?.address ?? bonding?.hill ?? claim?.reference.jobId ?? ""
        if case let .claimTransport(mode, table, _, _)? = plan?.intent { record = table + mode.rawValue }
        return .init(action: action, record: record,
            detail: withdrawal?.address ?? claim.map { "\($0.reference.role):\($0.reference.index)" } ?? "")
    }
    var label: String {
        if case let .claimTransport(mode, _, _, _)? = plan?.intent {
            return mode == .close ? Stage1Copy.closeTransport : mode == .deactivate ? Stage1Copy.deactivateTransport : Stage1Copy.transport
        }
        return action.label
    }
}

/// Shared native section, mounted beside legacy CAL and inside the three money
/// rooms. Its own loading/failure state cannot replace the containing surface.
struct Stage1Section: View {
    var climbID: String?
    var climbName: String?
    @Environment(AppSession.self) private var session
    @State private var model: Stage1Model
    @State private var selection: Stage1Selection?
    @State private var openLots: Set<String> = []
    init(climbID: String? = nil, climbName: String? = nil) {
        self.climbID = climbID; self.climbName = climbName
        #if DEBUG
        if Stage1RenderFixtureMode.current != nil {
            _model = State(initialValue: Stage1Model(service: Stage1FixtureService(), rpc: Stage1FixtureRPC(), store: Stage1RenderFixtureData.store))
            return
        }
        #endif
        _model = State(initialValue: Stage1Model())
    }
    private var owner: Stage1Owner? { Stage1Owner(session.currentUser) }
    private var loadKey: String { (owner?.key ?? "") + ":" + (climbID ?? "") }
    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if model.visible && (climbID != nil || owner != nil) {
                VStack(alignment: .leading, spacing: 0) {
                    SectionHeader(title: Stage1Copy.group).padding(.top, 24)
                    if climbID != nil { bondingRows }
                    if owner != nil, climbID == nil || model.hill != nil { ownerRows }
                }
                .accessibilityIdentifier("stage1-section")
            }
        }
        .task(id: loadKey) {
            #if DEBUG
            if Stage1RenderFixtureMode.current == nil && ProcessInfo.processInfo.arguments.contains(where: { $0.hasPrefix("-BR") && $0.hasSuffix("RenderFixture") }) { return }
            #endif
            await reload()
            while !Task.isCancelled && !model.hasNoHill(climbID) {
                do { try await Task.sleep(for: .seconds(30)) } catch { return }
                let wasVisible = model.visible
                let hadActions = model.actionsEnabled
                if await model.refreshGate(), !wasVisible || hadActions != model.actionsEnabled { await reload() }
            }
        }
        .task(id: loadKey) {
            while !Task.isCancelled {
                do { try await Task.sleep(for: .seconds(4)) } catch { return }
                if await model.reconcilePending(), selection == nil { await reload() }
            }
        }
        .onChange(of: owner?.key) { selection = nil }
        .onChange(of: model.visible) { if !model.visible { selection = nil } }
        .onChange(of: model.actionsEnabled) { if !model.actionsEnabled { selection = nil; openLots = [] } }
        .sheet(item: $selection, onDismiss: { Task { await reload() } }) { selected in
            if let owner, model.visible {
                Stage1ActionSheet(selection: selected, registry: model.registry, owner: owner,
                    service: model.service, rpc: model.rpc, store: model.store,
                    currentOwner: { Stage1Owner(session.currentUser) })
                    .presentationCornerRadius(Theme.crown)
            }
        }
    }
    private func reload() async { openLots = []; await model.load(climbID: climbID, owner: owner) }

    private func group<Content: View>(_ title: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            SectionHeader(title: title).padding(.top, 16)
            GroupCard { content() }
        }
    }
    @ViewBuilder private func state<T, Content: View>(_ value: Stage1Load<T>, @ViewBuilder content: (T) -> Content) -> some View {
        switch value {
        case .loading:
            ProgressView(Stage1Copy.loading).font(.body).foregroundStyle(Theme.gray).frame(maxWidth: .infinity, minHeight: Theme.row)
        case .unavailable:
            GrammarRow(label: Stage1Copy.unavailable)
            CenteredActionRow(label: "Try again") { Task { await reload() } }
        case let .loaded(value): content(value)
        }
    }
    private func action(_ selected: Stage1Selection) -> some View {
        CenteredActionRow(label: selected.label) { selection = selected }
            .accessibilityIdentifier("stage1-\(selected.action.rawValue)")
    }
    @ViewBuilder private func more(_ kind: String) -> some View {
        if model.more.contains(kind) {
            CenteredActionRow(label: model.loadingMore.contains(kind) ? Stage1Copy.loading : "Load more") { Task { await model.loadMore(kind) } }
                .disabled(model.loadingMore.contains(kind))
        }
    }
    private var bondingRows: some View {
        group(Stage1Copy.hillHeading) {
            state(model.bonding) { b in
                Stage1Fact(label: Stage1Copy.backing, value: Stage1MintRegistry.backing(b.assets).map { Format.baseUnits($0, decimals: 9) + " SOL" })
                if Stage1Numbers.uint(b.lineLamports) != nil { Stage1Fact(label: Stage1Copy.line, value: Format.baseUnits(b.lineLamports, decimals: 9) + " SOL") }
                if let bonded = b.bonded { GrammarRow(label: bonded ? Stage1Copy.bonded : Stage1Copy.unbonded) }
                if Stage1Numbers.uint(b.foundingCount) != nil { Stage1Fact(label: Stage1Copy.founders, value: Format.baseUnits(b.foundingCount, tokenDecimals: 0, decimals: 0)) }
                ForEach(Array(b.assets.enumerated()), id: \.offset) { _, asset in
                    if let amount = model.registry.amount(asset.weekPool?.available, mint: asset.mint) { Stage1Fact(label: Stage1Copy.pool, value: amount, detail: week(b.week)) }
                    if let amount = model.registry.amount(asset.weekPool?.pool, mint: asset.mint) { Stage1Fact(label: Stage1Copy.sharedPool, value: amount, detail: week(b.week)) }
                }
                if let split = b.split {
                    Stage1Fact(label: Stage1Copy.split, value: nil)
                    if let n = split.everyRiderByAscents { Stage1Fact(label: Stage1Copy.ascents, value: Format.number(Double(n), places: 0) + "%") }
                    if let n = split.topTen { Stage1Fact(label: "Leaderboard pool", value: Format.number(Double(n), places: 0) + "%") }
                    if let n = split.localLegend { Stage1Fact(label: "Local Legend", value: Format.number(Double(n), places: 0) + "%") }
                }
                if b.assets.isEmpty { GrammarRow(label: Stage1Copy.empty) }
            }
        }
    }
    private var ownerRows: some View {
        VStack(alignment: .leading, spacing: 0) {
            group(Stage1Copy.registration) {
                state(model.registration) { r in
                    GrammarRow(label: r.registration == nil ? Stage1Copy.unregistered : Stage1Copy.registered)
                    ForEach(Array(r.held.enumerated()), id: \.offset) { _, row in payRow(row, label: Stage1Copy.held) }
                    if model.actionsEnabled, r.registration == nil { action(.init(action: .registration, registration: r)) }
                }
            }
            paymentRows(model.pay, title: Stage1Copy.pay, kind: "pay")
            paymentRows(model.dung, title: "DUNG", kind: "dung")
            group(Stage1Copy.pledges) {
                state(model.pledges) { lots in
                    if lots.isEmpty { GrammarRow(label: Stage1Copy.empty) }
                    ForEach(lots) { lot in pledgeRows(lot) }
                    more("pledges")
                }
                if model.actionsEnabled, let b = model.bonding.value, !model.registry.stakingAssets(b).isEmpty {
                    action(.init(action: .pledge, climbName: climbName, bonding: b))
                }
            }
            if model.actionsEnabled {
              state(model.transports) { transports in
                if !transports.isEmpty || model.more.contains("lookups") {
                    group(Stage1Copy.transport) {
                        ForEach(transports) { row in
                            if let plan = row.plan { action(.init(action: .transport, plan: plan)) }
                            else {
                                GrammarRow(label: Stage1Copy.transport, value: "Pending")
                                CenteredActionRow(label: "Try again") { Task { await model.loadTransports() } }
                            }
                        }
                        more("lookups")
                    }
                }
              }
            }
        }
    }
    private func paymentRows(_ payments: Stage1Load<Stage1Payments>, title: String, kind: String) -> some View {
        group(title) {
            state(payments) { p in
                if p.paid.isEmpty && p.pending.isEmpty { GrammarRow(label: Stage1Copy.empty) }
                ForEach(Array(p.paid.enumerated()), id: \.offset) { _, row in payRow(row, label: Stage1Copy.paid) }
                ForEach(Array(p.pending.enumerated()), id: \.offset) { _, row in payRow(row, label: Stage1Copy.pending) }
                more(kind)
            }
            if model.actionsEnabled {
              state(model.claims) { claims in
                ForEach(claims.filter { $0.intent.claimType == (kind == "dung" ? "dung" : "cash") && (model.hill == nil || $0.intent.claims.allSatisfy { $0.hill == model.hill }) }) { claim in
                    action(.init(action: .selfClaim, climbName: climbName, claim: claim))
                }
            }
              more("claims")
            }
        }
    }
    private func week(_ raw: Stage1JSON?) -> String? {
        guard let s = raw?.text, Stage1Numbers.uint(s) != nil else { return nil }
        return "Week " + Format.baseUnits(s, tokenDecimals: 0, decimals: 0)
    }
    private func payRow(_ row: Stage1Pay, label: String) -> some View {
        Stage1Fact(label: label, value: model.registry.amount(row.amount, mint: row.mint, kind: row.kind),
            detail: [week(row.week), climbID == nil ? row.climbName : nil].compactMap { $0 }.joined(separator: " · "))
    }
    private func pledgeRows(_ lot: Stage1Pledge) -> some View {
        VStack(spacing: 0) {
            Stage1Fact(label: Stage1Copy.pledge, value: model.registry.amount(lot.units, mint: lot.mint),
                detail: [lot.stateLabel, climbID == nil ? lot.climbName : nil].compactMap { $0 }.joined(separator: " · "))
            if let weeks = lot.lockWeeks { Stage1Fact(label: Stage1Copy.lock, value: Format.number(Double(weeks), places: 0)) }
            if let end = Stage1Numbers.date(lot.lockEnd) { Stage1Fact(label: Stage1Copy.lockEnd, value: end) }
            if lot.founding == true { GrammarRow(label: Stage1Copy.founding) }
            ForEach(lot.withdrawals) { w in
                if let notice = Stage1Numbers.date(w.data.noticeAt) { Stage1Fact(label: Stage1Copy.notice, value: notice) }
                if let eligible = Stage1Numbers.date(w.data.eligibleAt) { Stage1Fact(label: Stage1Copy.eligible, value: eligible) }
                let labels = [Stage1Copy.noticePending, Stage1Copy.noticeExiting, Stage1Copy.noticeReturned, Stage1Copy.noticeCancelled]
                if let status = w.data.status, labels.indices.contains(status) { GrammarRow(label: labels[status]) }
            }
            if model.actionsEnabled, lot.cancelled == false, (Stage1Numbers.uint(lot.basisLamports) ?? 0) > 0 {
                CenteredActionRow(label: Stage1Copy.pledgeActions) {
                    if openLots.remove(lot.id) == nil {
                        openLots.insert(lot.id)
                        Task { await model.loadLotActions(lot.id) }
                    }
                }
                if openLots.contains(lot.id) {
                    if model.eligibilityLoading.contains(lot.id) { ProgressView(Stage1Copy.loading).padding(14) }
                    else if model.eligibilityFailures.contains(lot.id) {
                        GrammarRow(label: Stage1Copy.unavailable)
                        CenteredActionRow(label: "Try again") { Task { await model.loadLotActions(lot.id) } }
                    } else {
                        if lot.withdrawalsPausedUntil != nil && lot.withdrawals.contains(where: { $0.data.status == 0 || $0.data.status == 1 }) {
                            GrammarRow(label: Stage1Copy.withdrawalsPaused)
                                .accessibilityIdentifier("stage1-withdrawals-paused")
                        }
                        ForEach(Stage1Plans.actions(lot)) { a in
                            action(.init(action: a.action, climbName: lot.climbName ?? climbName, lot: lot, withdrawal: a.withdrawal))
                        }
                    }
                }
                Color.clear.frame(height: 0)
                    .task(id: openLots.contains(lot.id) ? lot.withdrawalsPausedUntil : nil) {
                        while openLots.contains(lot.id),
                              let raw = model.pledges.value?.first(where: { $0.id == lot.id })?.withdrawalsPausedUntil,
                              let until = Stage1Numbers.uint(raw) {
                            // Local time schedules a fresh server read; it never lifts the pause itself.
                            let delay = max(1, min(60, Double(until) - Date.now.timeIntervalSince1970))
                            do { try await Task.sleep(for: .seconds(delay)) } catch { return }
                            await model.loadLotActions(lot.id)
                        }
                    }
            }
            RowSeparator()
        }
    }
}

/// The same grouped row grammar, allowing exact long amounts to wrap rather
/// than truncate. At accessibility sizes the value follows its label.
struct Stage1Fact: View {
    let label: String
    let value: String?
    var detail: String?
    @Environment(\.dynamicTypeSize) private var size
    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            if size.isAccessibilitySize {
                Text(label).font(.body).foregroundStyle(Theme.ink)
                if let value { numeral(value) }
            } else {
                HStack(alignment: .firstTextBaseline, spacing: 12) {
                    Text(label).font(.body).foregroundStyle(Theme.ink)
                    Spacer(minLength: 8)
                    if let value { numeral(value).multilineTextAlignment(.trailing).layoutPriority(1) }
                }
            }
            if let detail, !detail.isEmpty { Text(detail).font(.caption).foregroundStyle(Theme.gray) }
        }
        .fixedSize(horizontal: false, vertical: true)
        .padding(.horizontal, 14).padding(.vertical, 12)
        .frame(maxWidth: .infinity, minHeight: Theme.row, alignment: .leading)
        .accessibilityElement(children: .combine)
    }
    private func numeral(_ value: String) -> some View {
        Text(value).font(.numeral(.body)).monospacedDigit().foregroundStyle(Theme.ink)
    }
}
