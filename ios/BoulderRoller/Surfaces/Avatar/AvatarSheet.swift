import SwiftUI

/// Surface 3 — Avatar sheet: identity, value, configuration. One room behind
/// the avatar (ChatGPT settings pattern). CAL is a fact you can't tap;
/// Settlements are value plus chevron; money never appears anywhere else
/// (Law 6: times are public, money is private).
struct AvatarSheet: View {
    @Environment(AppSession.self) private var session
    @Environment(\.dismiss) private var dismiss

    @State private var calBalance: String?
    @State private var uncollected: Double?
    /// False until the first gather lands (or cache hydrates) — rows redact.
    @State private var moneyRevealed = false
    @State private var showSettlements = false
    @State private var showUnitsEditor = false
    @State private var showSensors = false
    @State private var showWallet = false
    @State private var showDiagnostics = false
    @State private var showPrivacy = false
    @State private var showAccountDeletion = false
    @State private var showProfileEdit = false
    @State private var sensors = SensorManager.shared
    @State private var physiology = RiderPhysiology.empty
    @State private var editingWeight = false
    @State private var showThreshold = false
    @State private var thresholdDisplay: ThresholdDisplay?
    @State private var thresholdLoading = true
    @State private var thresholdReadFailed = false
    #if DEBUG
    @State private var devClimbs: [PopularClimb] = []
    @State private var devClimbId: String?
    @State private var devShowMyProfile = false
    #endif

    var body: some View {
        ZStack {
            Theme.sheet.ignoresSafeArea()
            ScrollView {
                VStack(spacing: 0) {
                    closeRow
                    identityHeader

                    VStack(alignment: .leading, spacing: 0) {
                        SectionHeader(title: "Riding")
                        GroupCard {
                            GrammarRow(
                                icon: "bolt",
                                label: "CAL balance",
                                value: moneyRevealed ? FiniteMoneyAmount(calBalance).display : "0.00",
                                valueIsNumeral: FiniteMoneyAmount(calBalance).isAvailable,
                                valueIsLoading: !moneyRevealed,
                                valueColor: Theme.ink
                            )
                            RowSeparator(inset: 48)
                            GrammarRow(
                                icon: "scroll",
                                label: "Settlements",
                                value: moneyRevealed ? uncollectedLabel : "0 DUNG",
                                valueIsNumeral: uncollected != nil,
                                valueIsLoading: !moneyRevealed,
                                chevron: true
                            ) {
                                showSettlements = true
                            }
                            RowSeparator(inset: 48)
                            GrammarRow(
                                icon: "wave.3.right",
                                label: "Sensors",
                                value: sensorsLabel,
                                chevron: true
                            ) {
                                showSensors = true
                            }
                            RowSeparator(inset: 48)
                            GrammarRow(
                                icon: "lock",
                                label: "Privacy",
                                chevron: true
                            ) {
                                showPrivacy = true
                            }
                            RowSeparator(inset: 48)
                            GrammarRow(
                                icon: "gauge.with.needle",
                                label: "Threshold",
                                value: thresholdRowValue,
                                valueIsNumeral: thresholdIsEstablished,
                                valueIsLoading: thresholdLoading && !thresholdReadFailed,
                                chevron: !thresholdReadFailed
                            ) {
                                if thresholdDisplay != nil {
                                    showThreshold = true
                                }
                            }
                            if thresholdReadFailed,
                               let riderID = session.currentUser?.id {
                                RowSeparator(inset: 0)
                                CenteredActionRow(label: "Retry") {
                                    Task { @MainActor in
                                        await retryThreshold(for: riderID, openOnSuccess: true)
                                    }
                                }
                            }
                            RowSeparator(inset: 48)
                            GrammarRow(
                                icon: "scalemass",
                                label: "Weight",
                                value: Format.weight(
                                    kg: physiology.weightKg,
                                    units: usesMetricUnits ? .metric : .imperial
                                ),
                                valueIsNumeral: physiology.weightKg != nil,
                                chevron: true
                            ) {
                                editingWeight = true
                            }
                            RowSeparator(inset: 48)
                            GrammarRow(
                                icon: "ruler",
                                label: "Units",
                                value: unitsLabel,
                                chevron: true
                            ) {
                                showUnitsEditor = true
                            }
                        }

                        Stage1Section().id(Stage1Owner(session.currentUser)?.key)

                        SectionHeader(title: "Account")
                            .padding(.top, 26)
                        GroupCard {
                            GrammarRow(
                                icon: "creditcard",
                                label: "Wallet",
                                value: walletLabel,
                                valueIsNumeral: session.currentUser?.wallet.isEmpty == false,
                                chevron: true
                            ) {
                                showWallet = true
                            }
                            RowSeparator(inset: 48)
                            GrammarRow(
                                icon: "stethoscope",
                                label: "Diagnostics",
                                chevron: true
                            ) {
                                showDiagnostics = true
                            }
                            RowSeparator(inset: 48)
                            GrammarRow(
                                icon: "envelope",
                                label: "Email",
                                value: {
                                    let email = session.currentUser?.email ?? ""
                                    return email.isEmpty ? "—" : email
                                }()
                            )
                            RowSeparator(inset: 48)
                            GrammarRow(
                                icon: "trash",
                                label: "Delete Account",
                                chevron: true
                            ) {
                                showAccountDeletion = true
                            }
                            RowSeparator(inset: 0)
                            // Centered action row — the Settings "Sign Out"
                            // species (constitution §4).
                            CenteredActionRow(label: "Sign out") {
                                Task {
                                    await session.signOut()
                                    dismiss()
                                }
                            }
                        }

                        #if DEBUG
                        // Developer tooling, DEBUG builds only: drive the
                        // share-sheet import pipeline from files placed in
                        // the app's Documents directory (simulators have no
                        // Files-app content by default). Same code path as
                        // the product entry (session.pendingImportURL).
                        Text("DEV")
                            .font(.caption2)
                            .foregroundStyle(Theme.gray3)
                            .padding(.top, 26)
                            .padding(.bottom, 8)
                        GroupCard {
                            ForEach(Array(devDocuments.enumerated()), id: \.element) { index, url in
                                if index > 0 { RowSeparator() }
                                GrammarRow(label: url.lastPathComponent, chevron: true) {
                                    dismiss()
                                    session.pendingImportURL = url
                                }
                            }
                            if devDocuments.isEmpty {
                                GrammarRow(label: "No files in Documents")
                            }
                        }
                        // DEBUG navigation into real canon climbs (a fresh
                        // account has no ride entry points yet).
                        GroupCard {
                            ForEach(Array(devClimbs.enumerated()), id: \.element.id) { index, climb in
                                if index > 0 { RowSeparator() }
                                GrammarRow(label: climb.name ?? climb.id, chevron: true) {
                                    devClimbId = climb.id
                                }
                            }
                        }
                        .padding(.top, 12)
                        GroupCard {
                            GrammarRow(label: "My profile", chevron: true) {
                                devShowMyProfile = true
                            }
                        }
                        .padding(.top, 12)
                        #endif
                    }
                    .padding(.horizontal, Theme.margin)
                    .padding(.top, 24)
                    .padding(.bottom, 32)
                }
            }
        }
        .sheet(isPresented: $showSettlements) {
            SettlementsView()
                .presentationCornerRadius(Theme.crown)
        }
        .sheet(isPresented: $showWallet) {
            WalletSheet()
                .presentationCornerRadius(Theme.crown)
        }
        .sheet(isPresented: $showDiagnostics) {
            DiagnosticsSheet()
                .presentationCornerRadius(Theme.crown)
        }
        .sheet(isPresented: $showSensors) {
            SensorPairingView()
                .presentationCornerRadius(Theme.crown)
        }
        .sheet(isPresented: $showPrivacy) {
            PrivacyView()
                .presentationCornerRadius(Theme.crown)
        }
        .sheet(isPresented: $showAccountDeletion) {
            AccountDeletionView()
                .presentationCornerRadius(Theme.crown)
        }
        .sheet(isPresented: $showProfileEdit) {
            ProfileEditSheet()
                .presentationCornerRadius(Theme.crown)
        }
        .sheet(isPresented: $showUnitsEditor) {
            UnitsEditSheet(usesMetric: usesMetricUnits)
                .presentationDetents([.medium])
                .presentationCornerRadius(Theme.crown)
        }
        .sheet(isPresented: $showThreshold) {
            if let thresholdDisplay, let riderID = session.currentUser?.id {
                ThresholdSheet(display: thresholdDisplay) {
                    beginThresholdBoundaryRefresh(for: riderID)
                }
                .presentationCornerRadius(Theme.crown)
            }
        }
        .sheet(isPresented: $editingWeight) {
            if let user = session.currentUser {
                PhysiologyEditSheet(
                    riderID: user.id,
                    usesMetricWeight: usesMetricUnits,
                    onChanged: { reloadPhysiology() }
                )
                .presentationCornerRadius(Theme.crown)
            }
        }
        #if DEBUG
        .sheet(item: $devClimbId) { climbId in
            NavigationStack { ClimbDetailView(climbId: climbId) }
                .presentationCornerRadius(Theme.crown)
        }
        .sheet(isPresented: $devShowMyProfile) {
            if let user = session.currentUser {
                NavigationStack { RiderProfileView(identifier: user.wallet) }
                    .presentationCornerRadius(Theme.crown)
            }
        }
        #endif
        .task(id: session.currentUser?.id) {
            #if DEBUG
            if Stage1RenderFixtureMode.current != nil {
                calBalance = "480"; uncollected = 12; moneyRevealed = true
                thresholdLoading = false
                return
            }
            #endif
            let riderID = session.currentUser?.id
            showThreshold = false
            thresholdDisplay = nil
            thresholdLoading = true
            thresholdReadFailed = false
            guard let riderID else { return }
            await load(riderID: riderID)
        }
    }

    private var closeRow: some View {
        HStack {
            Spacer()
            Button {
                dismiss()
            } label: {
                Image(systemName: "xmark")
                    .font(.footnote.weight(.semibold))
                    .foregroundStyle(Theme.ink)
                    .frame(width: 32, height: 32)
                    .background(Circle().fill(Theme.card))
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Close")
        }
        .padding(.horizontal, Theme.margin)
        .padding(.top, 14)
    }

    /// Identity header — the header is the tap, the pencil is the hint
    /// (row-grammar species at header scale). Opens the owner's profile
    /// editor: name, neighborhood, photo.
    private var identityHeader: some View {
        Button {
            showProfileEdit = true
        } label: {
            VStack(spacing: 2) {
                AvatarView(
                    name: session.currentUser?.shownName,
                    url: session.currentUser?.avatarUrl.flatMap(URL.init),
                    size: 58
                )
                HStack(spacing: 5) {
                    Text(session.currentUser?.shownName ?? "")
                        .font(.body.weight(.semibold))
                        .foregroundStyle(Theme.ink)
                    Image(systemName: "pencil")
                        .font(.caption2.weight(.semibold))
                        .foregroundStyle(Theme.gray3)
                        .accessibilityHidden(true)
                }
                .padding(.top, 8)
                if let location = session.currentUser?.location, !location.isEmpty {
                    Text(location)
                        .font(.caption2)
                        .foregroundStyle(Theme.gray)
                }
            }
            .padding(.top, 2)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Edit profile")
    }

    private var thresholdIsEstablished: Bool {
        if case .established = thresholdDisplay { return true }
        return false
    }

    private var thresholdRowValue: String {
        switch thresholdDisplay {
        case nil: return Format.threshold(nil)
        case .establishing?: return "Establishing"
        case let .established(currentW, _, _, _, _)?: return Format.threshold(currentW)
        }
    }

    private var sensorsLabel: String {
        let connected = sensors.connectedCount
        if connected > 0 { return "\(connected) Connected" }
        return sensors.myDevices.isEmpty ? "None" : "Not Connected"
    }

    private var uncollectedLabel: String {
        guard let uncollected else { return "—" }
        return uncollected > 0 ? "+\(Format.amount(uncollected, decimals: Precision.dung)) DUNG" : "0 DUNG"
    }

    private var usesMetricUnits: Bool {
        session.currentUser?.preferredUnits == "metric"
    }

    /// Truncated form for the row; the sheet shows the exact address.
    /// Absence is a dash, never an empty string.
    private var walletLabel: String {
        guard let wallet = session.currentUser?.wallet, !wallet.isEmpty
        else { return "—" }
        return "\(wallet.prefix(4))…\(wallet.suffix(4))"
    }

    private var unitsLabel: String {
        usesMetricUnits ? "Kilometers" : "Miles"
    }

    private func reloadPhysiology() {
        guard let user = session.currentUser else { return }
        physiology = RiderPhysiologyStore.load(riderID: user.id)
    }

    private func load(riderID: String) async {
        guard session.currentUser?.id == riderID else { return }
        thresholdLoading = true
        thresholdReadFailed = false
        reloadPhysiology()
        // Cached money paints at once (no dash-then-number flip on reopen);
        // the fresh gather replaces it in one reveal.
        if !moneyRevealed {
            async let cachedBalance: CalOnchainResponse? = try? await APIClient.shared.calBalance(policy: .cacheOnly)
            async let cachedUncollected: Double? = AppSession.uncollectedTotal(policy: .cacheOnly)
            let (hydratedBalance, hydratedUncollected) = await (cachedBalance, cachedUncollected)
            guard !Task.isCancelled, session.currentUser?.id == riderID else { return }
            if let hydratedBalance, hydratedUncollected != nil {
                calBalance = hydratedBalance.calBalance
                uncollected = hydratedUncollected
                moneyRevealed = true
            }
        }
        // Gather, then reveal together.
        async let balance: CalOnchainResponse? = try? await APIClient.shared.calBalance()
        async let nextUncollected: Double? = AppSession.uncollectedTotal()
        async let nextThreshold = session.refreshRiderThresholdAuthority(for: riderID)
        let (loadedBalance, loadedUncollected, loadedThreshold) = await (
            balance, nextUncollected, nextThreshold
        )
        guard !Task.isCancelled, session.currentUser?.id == riderID else { return }
        if let loadedBalance { calBalance = loadedBalance.calBalance }
        uncollected = loadedUncollected
        moneyRevealed = true
        thresholdDisplay = loadedThreshold
        thresholdLoading = false
        thresholdReadFailed = loadedThreshold == nil
        // Warm the Settlements room (one small read) so opening it is instant.
        Task.detached(priority: .utility) { _ = try? await APIClient.shared.myDistributions() }
        #if DEBUG
        if let popular = try? await APIClient.shared.popularClimbs() {
            devClimbs = popular.climbs ?? []
        }
        #endif
    }

    private func beginThresholdBoundaryRefresh(for riderID: String) {
        guard session.currentUser?.id == riderID else {
            showThreshold = false
            thresholdDisplay = nil
            return
        }
        showThreshold = false
        thresholdDisplay = nil
        thresholdLoading = true
        thresholdReadFailed = false
        Task { @MainActor in
            await retryThreshold(for: riderID, openOnSuccess: false)
        }
    }

    private func retryThreshold(for riderID: String, openOnSuccess: Bool) async {
        thresholdLoading = true
        thresholdReadFailed = false
        let loadedThreshold = await session.refreshRiderThresholdAuthority(for: riderID)
        guard !Task.isCancelled, session.currentUser?.id == riderID else { return }
        thresholdDisplay = loadedThreshold
        thresholdLoading = false
        thresholdReadFailed = loadedThreshold == nil
        if openOnSuccess, loadedThreshold != nil { showThreshold = true }
    }

    #if DEBUG
    private var devDocuments: [URL] {
        let docs = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask)[0]
        let files = (try? FileManager.default.contentsOfDirectory(
            at: docs, includingPropertiesForKeys: nil
        )) ?? []
        return files.filter { ["gpx", "fit", "tcx"].contains($0.pathExtension.lowercased()) }
    }
    #endif
}

/// Units editor — the source-picker species (two rows, one checkmark).
/// The server's preference is the truth; the sheet PATCHes and adopts the
/// returned account, never an optimistic value.
private struct UnitsEditSheet: View {
    let usesMetric: Bool

    @Environment(\.dismiss) private var dismiss
    @Environment(AppSession.self) private var session

    @State private var saving = false
    @State private var errorMessage: String?

    var body: some View {
        ZStack {
            Theme.sheet.ignoresSafeArea()
            VStack(alignment: .leading, spacing: 0) {
                SheetHeader(title: "Units") { dismiss() }
                    .padding(.top, 6)

                VStack(alignment: .leading, spacing: 0) {
                    GroupCard {
                        GrammarRow(
                            label: "Miles",
                            trailingSystemImage: usesMetric ? nil : "checkmark"
                        ) {
                            select(metric: false)
                        }
                        RowSeparator()
                        GrammarRow(
                            label: "Kilometers",
                            trailingSystemImage: usesMetric ? "checkmark" : nil
                        ) {
                            select(metric: true)
                        }
                    }
                    if let errorMessage {
                        GroupFooter(text: errorMessage)
                    }
                }
                .padding(.horizontal, Theme.margin)
                .padding(.top, 22)

                Spacer()
            }
        }
        .interactiveDismissDisabled(saving)
    }

    private func select(metric: Bool) {
        guard !saving else { return }
        guard metric != usesMetric else {
            dismiss()
            return
        }
        saving = true
        errorMessage = nil
        Task { @MainActor in
            defer { saving = false }
            do {
                let user = try await APIClient.shared.updatePreferredUnits(
                    metric ? "metric" : "imperial"
                )
                session.adoptUpdatedUser(user)
                dismiss()
            } catch {
                errorMessage = error.localizedDescription
            }
        }
    }
}
