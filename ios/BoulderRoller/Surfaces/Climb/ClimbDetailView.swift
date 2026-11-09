import MapKit
import SwiftUI

/// The ordinary rider destination for a canon climb. Sporting truth leads;
/// the attached Vault position stays compact and secondary.
///
/// Pushed on the content spine (sheets are for tasks and rooms). The money
/// sheets it presents stay sheets — they are transactions.
struct ClimbDetailView: View {
    let climbId: String
    @Environment(\.dismiss) private var dismiss
    @Environment(AppSession.self) private var session
    @Environment(\.units) private var units
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    @State private var climb: Climb?
    @State private var vaultDetail: VaultClimbDetail?
    @State private var results: VaultEffortHistoryResponse?
    @State private var positionTruth: ResolvedVaultPosition?
    @State private var legendName: String?
    @State private var showLeaderboard = false
    @State private var showMapViewer = false
    @State private var selectedRideId: String?
    @State private var riderProfileWallet: String?
    @State private var showDeposit = false
    @State private var showWithdraw = false
    @State private var loadFailed = false

    #if DEBUG
    private let renderFixture: BalanceClimbRenderFixture?
    #endif

    init(climbId: String) {
        self.climbId = climbId
        #if DEBUG
        renderFixture = nil
        #endif
    }

    #if DEBUG
    init(renderFixture: BalanceClimbRenderFixture) {
        climbId = renderFixture.climb.id
        self.renderFixture = renderFixture
        _climb = State(initialValue: renderFixture.climb)
        _vaultDetail = State(initialValue: renderFixture.vaultDetail)
        _results = State(initialValue: renderFixture.results)
        _positionTruth = State(initialValue: renderFixture.positionTruth)
        _legendName = State(initialValue: renderFixture.legendName)
    }
    #endif

    var body: some View {
        ZStack {
                Theme.sheet.ignoresSafeArea()
                if loadFailed, climb == nil {
                    VStack {
                        UnavailableCard(text: "Boulder Roller couldn’t load this climb.") {
                            Task { await load() }
                        }
                        Spacer()
                    }
                    .padding(.horizontal, Theme.margin)
                    .padding(.top, 22)
                } else if climb != nil {
                    ScrollView {
                        VStack(alignment: .leading, spacing: 0) {
                            identity
                            mapAndProfile
                            physicalFacts
                            yourResults
                            recordBoard
                            localLegend
                            vaultPosition
                            Stage1Section(climbID: climbId, climbName: climb?.name)
                                .id(Stage1Owner(session.currentUser)?.key)
                                .padding(.horizontal, Theme.margin)
                            Text("Climb data © OpenStreetMap contributors")
                                .font(.caption2)
                                .foregroundStyle(Theme.gray3)
                                .padding(.horizontal, 20)
                                .padding(.top, 20)
                        }
                        .padding(.bottom, 30)
                    }
                    .scrollEdgeEffectStyle(.hard, for: .top)
                }
            }
        .navigationTitle(climb?.name ?? "Climb")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar { toolbarContent }
        .navigationDestination(isPresented: $showLeaderboard) {
            LeaderboardView(
                climbName: climb?.name ?? "Climb",
                entries: boardEntries,
                myWallet: session.currentUser?.wallet,
                totalEfforts: totalClimbEfforts > 0 ? totalClimbEfforts : nil,
                climbId: climbId
            )
        }
        .navigationDestination(item: $selectedRideId) { rideId in
            RideDetailView(rideId: rideId)
        }
        .navigationDestination(item: $riderProfileWallet) { wallet in
            RiderProfileView(identifier: wallet)
        }
        .fullScreenCover(isPresented: $showMapViewer) {
            MapViewerView(
                fragments: routeFragments,
                title: climb?.name,
                subtitle: physicalSummary,
                destinationClimbId: nil,
                showsCanonAttribution: true
            )
        }
        .sheet(isPresented: $showDeposit) {
            if let vaultId = resolvedVaultId,
               let priorCalBaseUnits = depositBaseline
            {
                DepositSheet(
                    climbName: climb?.name ?? "Climb",
                    vaultId: vaultId,
                    depositedCal: depositedCal,
                    positionCal: positionAmount.value,
                    priorCalBaseUnits: priorCalBaseUnits,
                    onCompleted: { Task { await load() } }
                )
                .presentationCornerRadius(Theme.crown)
            }
        }
        .sheet(isPresented: $showWithdraw) {
            if let vaultId = resolvedVaultId, let myStake {
                WithdrawSheet(
                    climbName: climb?.name ?? "Climb",
                    vaultId: vaultId,
                    stake: myStake,
                    onCompleted: { Task { await load() } }
                )
                .presentationCornerRadius(Theme.crown)
            }
        }
        .task {
            #if DEBUG
            guard renderFixture == nil else { return }
            #endif
            await load()
        }
    }

    @ToolbarContentBuilder
    private var toolbarContent: some ToolbarContent {
        ToolbarItemGroup(placement: .topBarTrailing) {
            if let shareURL {
                ShareLink(item: shareURL) {
                    Label("Share Climb", systemImage: "square.and.arrow.up")
                }
            }
        }
    }

    private var shareURL: URL? {
        URL(string: "\(AppConfig.portalBaseURL)/climbs/\(climbId)")
    }

    @ViewBuilder
    private var identity: some View {
        if let region = climb?.region?.trimmingCharacters(in: .whitespacesAndNewlines),
           !region.isEmpty
        {
            Text(region)
                .font(.subheadline)
                .foregroundStyle(Theme.gray)
                .padding(.horizontal, 20)
                .padding(.vertical, 12)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
    }

    private var routeFragments: [[CLLocationCoordinate2D]] {
        RouteGeometry.fragments(from: climb?.routePreview)
    }

    @ViewBuilder
    private var mapAndProfile: some View {
        let profile = climb?.elevationProfile ?? []
        if !routeFragments.isEmpty {
            Button {
                showMapViewer = true
            } label: {
                RouteMapSnapshot(fragments: routeFragments)
                    .frame(height: 168)
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Open interactive map for \(climb?.name ?? "climb")")
        }
        if profile.count >= 2 {
            // Content-driven height: the card's shape is the climb's identity.
            // Max grade and gain live in the physical facts below — the figure
            // carries its own scale, so the old label row is gone.
            CanonProfileView(profile: profile)
                .padding(.horizontal, 20)
                .padding(.vertical, 16)
                .overlay(alignment: .bottom) {
                    Rectangle().fill(Theme.separator).frame(height: 0.5)
                }
        }
    }

    private struct ClimbMetric: Identifiable {
        let label: String
        let value: String
        let unit: String?
        var id: String { label }
    }

    private var metrics: [ClimbMetric] {
        var values: [ClimbMetric] = []
        if let length = climb?.lengthM {
            values.append(.init(label: "Distance", value: Format.distance(fromMeters: length, units: units), unit: units.distanceUnit))
        }
        if let gain = climb?.elevGainM {
            values.append(.init(label: "Elevation gain", value: Format.elevation(fromMeters: gain, units: units), unit: units.elevationUnit))
        }
        if let grade = climb?.avgGradientPct {
            values.append(.init(label: "Average grade", value: Format.gradeValue(grade), unit: "%"))
        }
        if let maximum = maxGradientPct {
            values.append(.init(label: "Maximum grade", value: Format.gradeValue(maximum), unit: "%"))
        }
        return values
    }

    @ViewBuilder
    private var physicalFacts: some View {
        if !metrics.isEmpty {
            LazyVGrid(
                columns: [GridItem(.adaptive(
                    minimum: dynamicTypeSize.isAccessibilitySize ? 220 : 130,
                    maximum: .infinity
                ), spacing: 20, alignment: .leading)],
                alignment: .leading,
                spacing: 16
            ) {
                ForEach(metrics) { metric in
                    VStack(alignment: .leading, spacing: 3) {
                        Text(metric.label)
                            .font(.caption)
                            .foregroundStyle(Theme.gray)
                        StatValueText(value: metric.value, unit: metric.unit)
                    }
                    .accessibilityElement(children: .combine)
                }
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 16)
            .overlay(alignment: .bottom) {
                Rectangle().fill(Theme.separator).frame(height: 0.5)
            }
        }
    }

    private var maxGradientPct: Double? {
        guard let profile = climb?.elevationProfile, profile.count >= 2 else { return nil }
        var maximum = 0.0
        for index in 1..<profile.count {
            let distance = profile[index].distanceM - profile[index - 1].distanceM
            let elevation = profile[index].elevationM - profile[index - 1].elevationM
            if distance > 5 { maximum = max(maximum, elevation / distance * 100) }
        }
        return maximum > 0 ? maximum : nil
    }

    private var physicalSummary: String? {
        metrics.map { metric in
            [metric.value, metric.unit].compactMap { $0 }.joined(separator: " ")
        }.prefix(3).joined(separator: " · ")
    }

    @ViewBuilder
    private var yourResults: some View {
        if let results, results.totalCount > 0 {
            sectionTitle("Your results")
            resultSummary(results)
            effortTrend(results)
            if !results.efforts.isEmpty {
                GroupCard {
                    ForEach(Array(results.efforts.enumerated()), id: \.element.id) { index, effort in
                        if index > 0 { RowSeparator(inset: 14) }
                        effortRow(effort)
                    }
                }
                .padding(.horizontal, Theme.margin)
            }
        }
    }

    private func resultSummary(_ results: VaultEffortHistoryResponse) -> some View {
        let facts: [(String, String)] = [
            ("Best", Format.climbTime(results.bestTimeSeconds)),
            ("Place", myBoardEntry?.sportingRankLabel ?? "—"),
            ("Attempts", "\(results.totalCount)"),
        ]
        return LazyVGrid(
            columns: [GridItem(.adaptive(
                minimum: dynamicTypeSize.isAccessibilitySize ? 220 : 96,
                maximum: .infinity
            ), spacing: 20, alignment: .leading)],
            alignment: .leading,
            spacing: 16
        ) {
            ForEach(facts, id: \.0) { label, value in
                VStack(alignment: .leading, spacing: 3) {
                    Text(label)
                        .font(.caption)
                        .foregroundStyle(Theme.gray)
                    Text(value)
                        .font(.numeral(.body))
                        .monospacedDigit()
                        .foregroundStyle(Theme.ink)
                }
                .accessibilityElement(children: .combine)
            }
        }
        .padding(.horizontal, 20)
        .padding(.bottom, 12)
    }

    /// Your times on this hill, drawn (Depth Ledger 2). Stable anatomy
    /// (ratified 2026-08-18): the section renders from the first dated
    /// effort — one is a dot, two a line, the trend earns its shape as
    /// history accrues. It never vanishes and waits.
    @ViewBuilder
    private func effortTrend(_ results: VaultEffortHistoryResponse) -> some View {
        let points = results.efforts.compactMap { effort -> EffortTrendChart.Point? in
            guard let date = Format.date(from: effort.achievedAt) else { return nil }
            return EffortTrendChart.Point(
                date: date,
                timeS: effort.timeSeconds,
                isPR: effort.isPR
            )
        }
        .sorted { $0.date < $1.date }
        if !points.isEmpty {
            EffortTrendChart(points: points)
                .frame(height: 120)
                .padding(.horizontal, 20)
                .padding(.bottom, 14)
        }
    }

    @ViewBuilder
    private func effortRow(_ effort: VaultEffortHistoryEntry) -> some View {
        if let rideId = effort.rideId {
            Button { selectedRideId = rideId } label: {
                effortRowContent(effort, showsChevron: true)
            }
            .buttonStyle(.plain)
        } else {
            effortRowContent(effort, showsChevron: false)
        }
    }

    private func effortRowContent(
        _ effort: VaultEffortHistoryEntry,
        showsChevron: Bool
    ) -> some View {
        let timestamp = Format.rideTimestamp(effort.achievedAt)
        return HStack(alignment: .top, spacing: 12) {
            VStack(alignment: .leading, spacing: 2) {
                Text(timestamp.isEmpty ? "Best effort" : timestamp)
                    .font(.subheadline)
                    .foregroundStyle(Theme.ink)
                    .fixedSize(horizontal: false, vertical: true)
                // One dot-joined line that wraps by whole facts — five
                // separate chips overflowed and broke words ("Per-sonal").
                effortFacts(effort)
                    .font(.caption2)
                    .foregroundStyle(Theme.gray2)
                    .fixedSize(horizontal: false, vertical: true)
                ClimbPowerLabel(power: Format.climbPower(effort))
                if dynamicTypeSize.isAccessibilitySize {
                    effortTime(effort)
                }
            }
            Spacer(minLength: 8)
            if !dynamicTypeSize.isAccessibilitySize { effortTime(effort) }
            if showsChevron {
                Image(systemName: "chevron.right")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(Theme.gray3)
                    .accessibilityHidden(true)
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 9)
        .frame(minHeight: 52)
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
    }

    private func effortTime(_ effort: VaultEffortHistoryEntry) -> some View {
        Text(Format.climbTime(effort.timeSeconds))
            .font(.numeral(.body))
            .monospacedDigit()
            .foregroundStyle(Theme.ink)
            .fixedSize()
    }

    private func effortFacts(_ effort: VaultEffortHistoryEntry) -> Text {
        var parts: [Text] = []
        if effort.isPR {
            parts.append(Text(Image(systemName: "medal")) + Text(" Personal best"))
        }
        if let improvement = effort.improvement, improvement > 0 {
            parts.append(Text("\(improvement)s faster"))
        }
        // Arithmetic from canon identity and the effort clock
        // (ratified 2026-08-18) — never from ride streams.
        if let length = climb?.lengthM, effort.timeSeconds > 0 {
            parts.append(Text(
                Format.speed(fromMps: length / effort.timeSeconds, units: units)
                    + " \(units.speedUnit)"
            ))
        }
        if let gain = climb?.elevGainM, gain > 0, effort.timeSeconds > 0 {
            parts.append(Text("\(Format.amount(gain / effort.timeSeconds * 3600)) VAM"))
        }
        guard let first = parts.first else { return Text("") }
        return parts.dropFirst().reduce(first) { $0 + Text(" · ") + $1 }
    }

    private var boardEntries: [RecordBoardEntry] {
        if let vaultDetail, !vaultDetail.leaderboard.isEmpty {
            return vaultDetail.leaderboard
        }
        return climb?.recordBoard?.entries ?? []
    }

    private var myBoardEntry: RecordBoardEntry? {
        guard let wallet = session.currentUser?.wallet else { return nil }
        return boardEntries.first { $0.wallet.caseInsensitiveCompare(wallet) == .orderedSame }
    }

    private var featuredBoardEntries: [RecordBoardEntry] {
        var featured = Array(boardEntries.prefix(3))
        if let mine = myBoardEntry,
           !featured.contains(where: { $0.wallet.caseInsensitiveCompare(mine.wallet) == .orderedSame })
        {
            featured.append(mine)
        }
        return featured
    }

    @ViewBuilder
    private var recordBoard: some View {
        // Stable anatomy (Law 11): a climb with a vault always carries its
        // Leaderboard section; with no times yet it degrades inside the
        // section instead of vanishing.
        if hasVault {
            if boardEntries.isEmpty {
                SectionHeader(title: "Leaderboard")
                    .padding(.horizontal, 20)
                    .padding(.top, 20)
                GroupCard {
                    Text("No times yet.")
                        .font(.body)
                        .foregroundStyle(Theme.gray)
                        .frame(maxWidth: .infinity, minHeight: Theme.row, alignment: .leading)
                        .padding(.horizontal, 14)
                }
                .padding(.horizontal, Theme.margin)
            } else {
                SectionHeader(title: "Leaderboard", trailing: "See All") {
                    showLeaderboard = true
                }
                .padding(.horizontal, 20)
                .padding(.top, 20)
                GroupCard {
                    ForEach(Array(featuredBoardEntries.enumerated()), id: \.element.id) { index, entry in
                        if index > 0 { RowSeparator(inset: 58) }
                        boardRow(entry)
                    }
                }
                .padding(.horizontal, Theme.margin)
            }
        }
    }

    private func boardRow(_ entry: RecordBoardEntry) -> some View {
        LeaderboardEntryRow(
            entry: entry,
            isMe: (session.currentUser?.wallet).map {
                entry.wallet.caseInsensitiveCompare($0) == .orderedSame
            } ?? false,
            dateLine: Format.monthYear(entry.achievedAt)
        ) {
            riderProfileWallet = entry.wallet
        }
    }

    private var currentLegend: LocalLegendStatus? {
        let legend = vaultDetail?.localLegend ?? climb?.localLegend
        guard let legend,
              let wallet = legend.wallet,
              !wallet.isEmpty,
              legend.isActive != false,
              legend.seatStatus != "inactive",
              legend.seatStatus != "none"
        else { return nil }
        return legend
    }

    @ViewBuilder
    private var localLegend: some View {
        if let legend = currentLegend, let wallet = legend.wallet {
            sectionTitle("Local Legend")
            GroupCard {
                Button { riderProfileWallet = wallet } label: {
                    HStack(spacing: 12) {
                        AvatarView(name: legendDisplayName(wallet), size: 38)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(legendDisplayName(wallet))
                                .font(.body.weight(.semibold))
                                .foregroundStyle(Theme.ink)
                            Text(legendDetail(legend))
                                .font(.caption)
                                .foregroundStyle(Theme.gray)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                        Spacer(minLength: 8)
                        Image(systemName: "chevron.right")
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(Theme.gray3)
                            .accessibilityHidden(true)
                    }
                    .padding(.horizontal, 14)
                    .padding(.vertical, 10)
                    .frame(minHeight: 58)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityElement(children: .combine)
            }
            .padding(.horizontal, Theme.margin)
        }
    }

    private func legendDisplayName(_ wallet: String) -> String {
        legendName ?? "Rider \(wallet.prefix(4))"
    }

    private func legendDetail(_ legend: LocalLegendStatus) -> String {
        if legend.isBootstrap == true { return "Founder stewardship" }
        var parts: [String] = []
        if let count = legend.completionsCount, count > 0 {
            parts.append("\(count) recent completion\(count == 1 ? "" : "s")")
        }
        if !Format.monthYear(legend.termEndsAt).isEmpty {
            parts.append("through \(Format.monthYear(legend.termEndsAt))")
        }
        return parts.isEmpty ? "Current steward" : parts.joined(separator: " · ")
    }

    @ViewBuilder
    private var vaultPosition: some View {
        if hasVault {
            sectionTitle("Vault")
            GroupCard {
                GrammarRow(
                    label: "Deposited",
                    value: depositedAmount.calDisplay,
                    valueIsNumeral: depositedAmount.isAvailable,
                    valueColor: Theme.ink
                )
                RowSeparator()
                if session.balanceActions.withdraw, withdrawBaseline != nil {
                    GrammarRow(
                        label: "Your position",
                        value: positionAmount.calDisplay,
                        valueIsNumeral: positionAmount.isAvailable,
                        valueColor: Theme.ink,
                        chevron: true
                    ) { showWithdraw = true }
                } else {
                    GrammarRow(
                        label: "Your position",
                        value: positionAmount.calDisplay,
                        valueIsNumeral: positionAmount.isAvailable,
                        valueColor: Theme.ink
                    )
                }
                if resolvedVaultId != nil,
                   depositBaseline != nil,
                   session.balanceActions.deposit
                {
                    RowSeparator(inset: 0)
                    CenteredActionRow(label: "Deposit") { showDeposit = true }
                }
            }
            .padding(.horizontal, Theme.margin)
            GroupFooter(
                text: "Deposits count from the next settlement week — Monday 12:00 UTC. The Local Legend seat follows completions over an eight-week term."
            )
            .padding(.horizontal, 20)
        }
    }

    private func sectionTitle(_ title: String) -> some View {
        SectionHeader(title: title)
            .padding(.horizontal, 20)
            .padding(.top, 20)
    }

    private var hasVault: Bool {
        vaultDetail != nil || climb?.hasVault == true || climb?.vaultEconomy?.hasVault == true
    }

    private var totalClimbEfforts: Int {
        vaultDetail?.totalCompletions ?? climb?.vaultEconomy?.totalCompletions ?? 0
    }

    private var depositedCal: String? {
        vaultDetail?.totalCalStaked ?? climb?.vaultEconomy?.totalCalStaked ?? climb?.totalCalStaked
    }

    private var myStake: VaultStake? { positionTruth?.stake }
    private var depositedAmount: FiniteMoneyAmount { FiniteMoneyAmount(depositedCal) }
    private var positionAmount: FiniteMoneyAmount { FiniteMoneyAmount(myStake?.calStaked) }
    private var resolvedVaultId: Int? { climb?.vaultEconomy?.vaultId ?? climb?.vaultId }
    private var depositBaseline: String? { positionTruth?.depositPriorCalBaseUnits }
    private var withdrawBaseline: Double? { positionTruth?.withdrawPositionCal }

    @MainActor
    private struct Assembled {
        let climb: Climb
        let vaultDetail: VaultClimbDetail?
        let results: VaultEffortHistoryResponse?
        let position: ResolvedVaultPosition?
        let legendName: String?
    }

    /// Stale-while-revalidate: a revisit renders instantly from the session
    /// cache, then the fresh read replaces it quietly. Either way every
    /// section lands together — never in stages (Tim, 2026-08-21).
    private func load() async {
        loadFailed = false
        if climb == nil, let cached = try? await assemble(policy: .cacheOnly) {
            apply(cached)
        }
        do {
            let fresh = try await assemble(policy: .network)
            await session.refreshBalanceActions()
            apply(fresh)
            // Warm the profiles a rider is likeliest to tap next (reads only).
            let wallets = featuredBoardEntries.prefix(4).map(\.wallet)
            Task.detached(priority: .utility) {
                for wallet in wallets {
                    _ = try? await APIClient.shared.riderProfile(identifier: wallet)
                }
            }
        } catch {
            loadFailed = climb == nil
        }
    }

    private func apply(_ assembled: Assembled) {
        vaultDetail = assembled.vaultDetail
        results = assembled.results
        positionTruth = assembled.position
        legendName = assembled.legendName
        // `climb` last: it is the gate the body renders on.
        climb = assembled.climb
    }

    private func assemble(policy: CachePolicy) async throws -> Assembled {
        let loadedClimb = try await APIClient.shared.climb(id: climbId, policy: policy)
        guard let vaultId = loadedClimb.vaultEconomy?.vaultId ?? loadedClimb.vaultId else {
            return Assembled(
                climb: loadedClimb, vaultDetail: nil, results: nil, position: nil, legendName: nil
            )
        }
        async let detailRequest: VaultClimbDetail? = try? await APIClient.shared.climbVaultDetail(vaultId: vaultId, policy: policy)
        async let resultsRequest: VaultEffortHistoryResponse? = try? await APIClient.shared.myClimbResults(vaultId: vaultId, policy: policy)
        async let stakesRequest: MyVaultStakesResponse? = try? await APIClient.shared.myStakes(policy: policy)
        let (loadedVault, loadedResults, loadedStakes) = await (
            detailRequest, resultsRequest, stakesRequest
        )

        var loadedPosition: ResolvedVaultPosition?
        if let stakes = loadedStakes?.stakes {
            loadedPosition = try? await VaultPositionTruthResolver.resolve(
                stakes: stakes,
                vaultId: vaultId,
                resolveLegacy: { signature in
                    try await VaultDirectory.vaultId(forSignature: signature)
                }
            )
        }

        var loadedLegendName: String?
        if let wallet = (loadedVault?.localLegend ?? loadedClimb.localLegend)?.wallet,
           let profile = try? await APIClient.shared.riderProfile(identifier: wallet, policy: policy)
        {
            loadedLegendName = profile.profile.shownName
        }
        return Assembled(
            climb: loadedClimb, vaultDetail: loadedVault, results: loadedResults,
            position: loadedPosition, legendName: loadedLegendName
        )
    }
}
