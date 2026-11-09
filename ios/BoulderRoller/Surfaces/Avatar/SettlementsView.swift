import SwiftUI

/// Surface 12 — Settlements. Uncollected up top with the Collect action,
/// history below in gray — luminance splits pending from past.
struct SettlementsView: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(AppSession.self) private var session

    @State private var uncollected: Double?
    @State private var history: [DistributionGroup] = []
    @State private var moneyRevealed = false
    @State private var money = MoneyModel()
    @State private var selectedWeek: DistributionGroup?

    #if DEBUG
    private let renderFixture: BalanceSettlementsRenderFixture?
    #endif

    init() {
        #if DEBUG
        renderFixture = nil
        #endif
    }

    #if DEBUG
    init(renderFixture: BalanceSettlementsRenderFixture) {
        self.renderFixture = renderFixture
        _uncollected = State(initialValue: renderFixture.uncollected)
        _moneyRevealed = State(initialValue: true)
        _history = State(initialValue: renderFixture.history)
        _money = State(initialValue: MoneyModel(renderStatus: renderFixture.status))
    }
    #endif

    var body: some View {
        NavigationStack {
            content
                .toolbar(.hidden, for: .navigationBar)
                .navigationDestination(item: $selectedWeek) { group in
                    SettlementWeekView(
                        group: group,
                        collectRow: (
                            available: collectRowAvailable,
                            action: { selectedWeek = nil; collect() }
                        )
                    )
                }
        }
    }

    /// The room shows Collect exactly under these conditions; the pushed
    /// week reuses the same test and the same action.
    private var collectRowAvailable: Bool {
        guard let uncollected, uncollected > 0 else { return false }
        return session.balanceActions.collect && money.canSubmit
    }

    private var content: some View {
        ZStack {
            Theme.sheet.ignoresSafeArea()
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    SheetHeader(title: "Settlements") { dismiss() }
                        .padding(.top, 6)

                    VStack(alignment: .leading, spacing: 0) {
                        GroupCard {
                            GrammarRow(
                                label: "Uncollected",
                                value: moneyRevealed ? uncollectedLabel : "0 DUNG",
                                valueIsNumeral: uncollected != nil,
                                valueIsLoading: !moneyRevealed,
                                valueColor: Theme.ink
                            )
                            if let uncollected, uncollected > 0,
                               session.balanceActions.collect {
                                RowSeparator(inset: 0)
                                if let statusLabel {
                                    HStack(spacing: 10) {
                                        if money.isWorking {
                                            ProgressView()
                                                .controlSize(.small)
                                                .tint(Theme.gray)
                                        }
                                        Text(statusLabel)
                                            .font(.body)
                                            .foregroundStyle(Theme.gray)
                                    }
                                    .frame(maxWidth: .infinity, minHeight: Theme.row)
                                } else if money.canSubmit {
                                    // Centered blue text row — the grouped
                                    // action species (constitution §4).
                                    CenteredActionRow(label: "Collect") {
                                        collect()
                                    }
                                }
                            }
                        }

                        GroupFooter(text: "Collecting takes a 5% fee.")

                        if case let .failed(message) = money.status {
                            GroupFooter(text: message)
                        }

                        if !history.isEmpty {
                            SectionHeader(title: "History")
                                .padding(.top, 24)
                            GroupCard {
                                ForEach(Array(history.enumerated()), id: \.element.id) { index, group in
                                    if index > 0 { RowSeparator() }
                                    // Rider's own total for the week —
                                    // exact receipt sum, not the vault-wide
                                    // distribution — with the week's detail
                                    // one push deeper (L2.10).
                                    GrammarRow(
                                        label: Format.weekOf(group.distributedAt),
                                        value: riderShareLabel(group),
                                        valueIsNumeral: true,
                                        chevron: true
                                    ) {
                                        selectedWeek = group
                                    }
                                }
                            }
                        }

                        GroupFooter(text: "Distributions settle Monday 12:00 UTC.")
                        Stage1Section().id(Stage1Owner(session.currentUser)?.key)
                    }
                    .padding(.horizontal, Theme.margin)
                    .padding(.top, 22)
                    .padding(.bottom, 32)
                }
            }
        }
        .task {
            #if DEBUG
            guard renderFixture == nil else { return }
            #endif
            await load()
        }
        .onChange(of: money.status) {
            if case .done = money.status {
                Task {
                    await load()
                    await session.refreshSettlementDot()
                }
            }
        }
    }

    private func collect() {
        guard session.balanceActions.collect,
              money.canSubmit,
              let wallet = session.currentUser?.wallet
        else { return }
        Task { await money.collectAll(wallet: wallet) }
    }

    private func load() async {
        // Cached history and uncollected paint at once; the fresh read
        // replaces them in one reveal.
        if history.isEmpty,
           let cached = try? await APIClient.shared.myDistributions(policy: .cacheOnly)
        {
            history = cached.distributions ?? []
        }
        if !moneyRevealed, let cachedUncollected = await AppSession.uncollectedTotal(policy: .cacheOnly) {
            uncollected = cachedUncollected
            moneyRevealed = true
        }
        // Gather, then reveal together — the room never updates piecemeal
        // (uncollected flipping before history on a post-collect refresh).
        async let balance: Void = session.refreshBalanceActions()
        async let nextUncollected: Double? = AppSession.uncollectedTotal()
        async let nextHistory: MyDistributionsResponse? = try? await APIClient.shared.myDistributions()
        let (_, loadedUncollected, loadedHistory) = await (balance, nextUncollected, nextHistory)
        uncollected = loadedUncollected
        moneyRevealed = true
        if let loadedHistory { history = loadedHistory.distributions ?? [] }
    }

    private var uncollectedLabel: String {
        guard let uncollected else { return "—" }
        return "+\(Format.amount(uncollected, decimals: Precision.dung)) DUNG"
    }

    /// The rider's own week total — never the vault-wide distribution
    /// total the old row showed, and never through binary float.
    private func riderShareLabel(_ group: DistributionGroup) -> String {
        SettlementFacts.riderShare(group.receipts).map { "+\($0) DUNG" } ?? "—"
    }

    private var statusLabel: String? {
        switch money.status {
        case .working: return "Collecting…"
        case .pending: return "Pending"
        case .delayed: return "Delayed"
        case .needsReview: return "Needs review"
        case .idle, .done, .failed: return nil
        }
    }
}
