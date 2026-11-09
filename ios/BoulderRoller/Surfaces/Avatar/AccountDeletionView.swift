import SwiftUI

/// N14: Tim delegated this as functional copy 2026-08-29 — a plain warning,
/// not ceremony. Veto window stays open until the next iOS build ships.
enum AccountDeletionConsentCopy {
    static let unuploadedRideRemoval: String? =
        "These rides were never uploaded. Deleting your account permanently destroys the only copies."

    static func hasRequiredRemovalCopy(
        for inventory: AccountDeletionLocalInventory
    ) -> Bool {
        inventory.rides.isEmpty || unuploadedRideRemoval != nil
    }

    static func acknowledgesRemoval(
        of inventory: AccountDeletionLocalInventory,
        reviewed: Bool
    ) -> Bool {
        reviewed && hasRequiredRemovalCopy(for: inventory)
    }
}

enum AccountDeletionPresentation {
    enum Remedy: Hashable {
        case reviewSettlements
        case openBalance
        case retry
        case contactSupport
    }

    static func statusLabel(_ status: AccountDeletionStatus) -> String {
        switch status.status {
        case .queued: return "Queued"
        case .processing: return "In Progress"
        case .blocked: return "Blocked"
        case .failedRetryable:
            return status.retryable ? "Try Again" : "Recovering"
        case .needsSupport: return "Needs Support"
        case .legacyUnverified: return "Needs Review"
        case .completed: return "Completed"
        }
    }

    static func pollsAutomatically(_ status: AccountDeletionStatus) -> Bool {
        status.status == .queued
            || status.status == .processing
            || (status.status == .failedRetryable && !status.retryable)
    }

    static func showsProgress(_ status: AccountDeletionStatus) -> Bool {
        pollsAutomatically(status)
    }

    static func offersSupport(_ status: AccountDeletionStatus) -> Bool {
        status.status == .needsSupport
            || status.status == .legacyUnverified
            || (status.status == .blocked && !status.retryable)
    }

    static func remedies(for blockers: [AccountDeletionBlocker]) -> Set<Remedy> {
        var remedies = Set<Remedy>()
        if blockers.contains(where: { $0.category == "claim" }) {
            remedies.insert(.reviewSettlements)
        }
        if blockers.contains(where: { $0.action == "open_balance" }) {
            remedies.insert(.openBalance)
        }
        if blockers.contains(where: { $0.action == "retry" }) {
            remedies.insert(.retry)
        }
        if blockers.contains(where: { $0.action == "contact_support" }) {
            remedies.insert(.contactSupport)
        }
        return remedies
    }

    static func blockerLabel(_ blocker: AccountDeletionBlocker) -> String {
        switch blocker.code {
        case "balance_remains":
            return blocker.asset.map { "\($0) Balance" } ?? "Balance"
        case "stake_remains": return "Active Stakes"
        case "claim_remains": return "Unclaimed DUNG"
        case "unuploaded_rides_unacknowledged": return "Ride Recordings"
        case "preflight_unavailable": return "Server Check"
        case "policy_review_required": return "Account Review"
        default: return "Account Requirement"
        }
    }

    static func failureLabel(_ failureCode: String?) -> String {
        switch failureCode {
        case "preflight_unavailable": return "Account Check Unavailable"
        case "queue_unavailable": return "Request Queue Unavailable"
        case nil: return "Previous Attempt"
        default: return "Previous Attempt Could Not Finish"
        }
    }
}

enum AccountDeletionHeaderPolicy {
    static func settingsDoneEnabled(isWorking: Bool) -> Bool { !isWorking }

    static func recoveryDoneEnabled(
        record: AccountDeletionSessionRecord
    ) -> Bool {
        record.localCleanupCompletedAt != nil
    }
}

struct AccountDeletionView: View {
    @Environment(AppSession.self) private var session
    @Environment(\.dismiss) private var dismiss
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.openURL) private var openURL

    let allowsDismiss: Bool

    @State private var model = AccountDeletionModel()
    @State private var reviewedRecordings = false
    @State private var confirmingDeletion = false
    @State private var showSettlements = false
    @State private var showDiagnostics = false

    init(allowsDismiss: Bool = true) {
        self.allowsDismiss = allowsDismiss
    }

    private var owner: RecordingOwner? {
        session.currentUser.map(RecordingOwner.init(user:))
    }

    private var lifecycleRequestID: String {
        selectedRequestID
            ?? owner.map { "new:\($0.id):\($0.wallet)" }
            ?? "none"
    }

    private var selectedRequestID: String? {
        session.accountDeletionCapabilityState.capability?.requestID
    }

    var body: some View {
        ZStack {
            Theme.sheet.ignoresSafeArea()
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    header
                        .padding(.top, 6)
                    content
                        .padding(.horizontal, Theme.margin)
                        .padding(.top, 22)
                        .padding(.bottom, 32)
                }
            }
        }
        .task(id: lifecycleRequestID) {
            let configuredOwner = session
                .accountDeletionCapabilityState.capability?.owner ?? owner
            model.configure(
                inventory: {
                    guard let inventoryOwner = configuredOwner else {
                        throw APIError.notAuthenticated
                    }
                    return try await session.accountDeletionInventory(
                        owner: inventoryOwner
                    )
                },
                localCleanup: { capability, status in
                    try await session.completeLocalAccountDeletion(
                        capability: capability,
                        status: status
                    )
                },
                capabilityDidChange: {
                    try await session.accountDeletionCapabilityDidChange(
                        expectedOwner: configuredOwner
                    )
                },
                localCleanupDidComplete: { owner in
                    try await session.accountDeletionLocalCleanupDidComplete(owner: owner)
                },
                acceptedStatusDiscarded: { owner in
                    try await session.preserveFenceForRemovedAccountDeletionStatus(
                        owner: owner
                    )
                }
            )
            await model.load(owner: owner, requestID: selectedRequestID)
        }
        .task(id: pollingID) {
            guard pollingID != nil else { return }
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(model.pollDelaySeconds))
                guard !Task.isCancelled else { return }
                await model.pollStatus()
            }
        }
        .onChange(of: readyInventoryDigest) { old, new in
            if old != new { reviewedRecordings = false }
        }
        .confirmationDialog(
            "Delete Account?",
            isPresented: $confirmingDeletion,
            titleVisibility: .visible
        ) {
            Button("Delete Account", role: .destructive) {
                guard let owner,
                      case let .ready(_, inventory) = model.state,
                      AccountDeletionConsentCopy.acknowledgesRemoval(
                        of: inventory,
                        reviewed: reviewedRecordings
                      )
                else { return }
                Task {
                    await model.requestDeletion(
                        owner: owner,
                        reviewedInventoryDigest: inventory.digest,
                        unuploadedRidesAcknowledged: true
                    )
                }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("Your identity and personal data will be removed. Your climb times, leaderboard history, and settled economics will remain linked to an anonymous account.")
            if readyInventoryHasRides,
               let removalConsent = AccountDeletionConsentCopy.unuploadedRideRemoval {
                Text(removalConsent)
            }
        }
        .sheet(isPresented: $showSettlements) {
            SettlementsView()
                .presentationCornerRadius(Theme.crown)
        }
        .sheet(isPresented: $showDiagnostics) {
            DiagnosticsSheet()
                .presentationCornerRadius(Theme.crown)
        }
        .interactiveDismissDisabled(isWorking || !allowsDismiss)
    }

    @ViewBuilder
    private var header: some View {
        if allowsDismiss {
            SheetHeader(
                title: "Delete Account",
                doneEnabled: AccountDeletionHeaderPolicy.settingsDoneEnabled(
                    isWorking: isWorking
                )
            ) { dismiss() }
        } else {
            SheetHeader(
                title: "Account Deletion",
                doneEnabled: isCompleted
            ) {
                Task { await model.acknowledgeCompletion() }
            }
        }
    }

    @ViewBuilder
    private var content: some View {
        switch model.state {
        case .loading:
            statusCard(label: "Checking", showsProgress: true)

        case let .ready(preflight, inventory):
            readyContent(preflight: preflight, inventory: inventory)

        case let .retryReview(status, inventory):
            retryReviewContent(status: status, inventory: inventory)

        case .requesting:
            statusCard(label: "Submitting", showsProgress: true)

        case let .tracking(status):
            trackingContent(status)

        case .requestNotFound:
            statusCard(label: "Request Not Found")
            actionCard(label: "Try Again") {
                Task { await model.reissueDeletion() }
            }
            if model.canDiscardSavedStatus { discardAction }
            supportAction
            diagnosticsAction

        case .statusUnavailable:
            statusCard(label: "Status Unavailable")
            actionCard(label: "Retry") {
                Task {
                    await model.load(owner: owner, requestID: selectedRequestID)
                }
            }
            if model.canDiscardSavedStatus { discardAction }
            supportAction
            diagnosticsAction

        case .storageUnavailable:
            statusCard(label: "Recovery Unavailable")
            actionCard(label: "Try Again") {
                Task {
                    await session.reloadAccountDeletionStorage()
                    await model.load(owner: owner, requestID: selectedRequestID)
                }
            }
            supportAction
            diagnosticsAction

        case .ownerMismatch:
            statusCard(label: "Account Deletion Unavailable")
            supportAction
            diagnosticsAction

        case .supportRequired:
            statusCard(label: "Needs Support")
            if model.canDiscardSavedStatus { discardAction }
            supportAction
            diagnosticsAction

        case .clearingLocalData:
            statusCard(label: "Finishing", showsProgress: true)

        case .localCleanupFailed:
            statusCard(label: "Local Cleanup Failed")
            actionCard(label: "Try Again") {
                Task { await model.refreshStatus() }
            }
            supportAction
            diagnosticsAction

        case .completed:
            statusCard(label: "Completed")

        case .completedLocally:
            statusCard(label: "Completed")

        case .discarded:
            statusCard(label: "Saved Status Removed")
        }
    }

    @ViewBuilder
    private func readyContent(
        preflight: AccountDeletionPreflight,
        inventory: AccountDeletionLocalInventory
    ) -> some View {
        let remedies = AccountDeletionPresentation.remedies(for: preflight.blockers)
        SectionHeader(title: "Status")
        GroupCard {
            GrammarRow(
                label: "Server Check",
                value: preflightLabel(preflight)
            )
            forEachBlocker(preflight.blockers)
        }

        SectionHeader(title: "Ride Recordings")
            .padding(.top, 26)
        GroupCard {
            if inventory.rides.isEmpty {
                GrammarRow(label: "Unuploaded Rides", value: "None")
            } else {
                ForEach(Array(inventory.rides.enumerated()), id: \.element.id) { index, ride in
                    if index > 0 { RowSeparator() }
                    GrammarRow(
                        label: rideTitle(ride),
                        value: "Unuploaded"
                    )
                }
            }
            RowSeparator(inset: 0)
            GrammarRow(
                label: "Ride Recordings Reviewed",
                trailingSystemImage: reviewedRecordings ? "checkmark" : nil
            ) {
                reviewedRecordings.toggle()
            }
            if !AccountDeletionConsentCopy.hasRequiredRemovalCopy(for: inventory) {
                RowSeparator(inset: 0)
                GrammarRow(label: "Removal Confirmation", value: "Pending")
            }
        }

        if preflight.isAvailableToFile,
           AccountDeletionConsentCopy.hasRequiredRemovalCopy(for: inventory) {
            GroupCard {
                CenteredActionRow(label: "Delete Account", color: .red) {
                    guard reviewedRecordings else { return }
                    confirmingDeletion = true
                }
            }
            .padding(.top, 20)
        }
        if remedies.contains(.reviewSettlements) {
            actionCard(label: "Review Settlements") { showSettlements = true }
        }
        if remedies.contains(.openBalance) {
            actionCard(label: "Open Balance") {
                openURL(AppConfig.portalBalanceURL)
            }
        }
        if remedies.contains(.retry) {
            actionCard(label: "Retry") {
                Task {
                    await model.load(owner: owner, requestID: selectedRequestID)
                }
            }
        }
        if remedies.contains(.contactSupport) {
            supportAction
        }
        diagnosticsAction
    }

    @ViewBuilder
    private func retryReviewContent(
        status: AccountDeletionStatus,
        inventory: AccountDeletionLocalInventory
    ) -> some View {
        statusCard(label: AccountDeletionPresentation.statusLabel(status))
        SectionHeader(title: "Ride Recordings")
            .padding(.top, 26)
        GroupCard {
            if inventory.rides.isEmpty {
                GrammarRow(label: "Unuploaded Rides", value: "None")
            } else {
                ForEach(Array(inventory.rides.enumerated()), id: \.element.id) { index, ride in
                    if index > 0 { RowSeparator() }
                    GrammarRow(label: rideTitle(ride), value: "Unuploaded")
                }
            }
            RowSeparator(inset: 0)
            GrammarRow(
                label: "Ride Recordings Reviewed",
                trailingSystemImage: reviewedRecordings ? "checkmark" : nil
            ) {
                reviewedRecordings.toggle()
            }
            if !AccountDeletionConsentCopy.hasRequiredRemovalCopy(for: inventory) {
                RowSeparator(inset: 0)
                GrammarRow(label: "Removal Confirmation", value: "Pending")
            }
        }
        if status.status == .completed,
           AccountDeletionConsentCopy.acknowledgesRemoval(
            of: inventory,
            reviewed: reviewedRecordings
           ) {
            actionCard(label: "Clear Local Data") {
                Task {
                    await model.acknowledgeCompletedInventory(
                        reviewedInventoryDigest: inventory.digest,
                        unuploadedRidesAcknowledged: true
                    )
                }
            }
        } else if status.retryable,
                  AccountDeletionConsentCopy.acknowledgesRemoval(
            of: inventory,
            reviewed: reviewedRecordings
           ) {
            actionCard(label: "Retry Deletion") {
                Task {
                    await model.retry(
                        reviewedInventoryDigest: inventory.digest,
                        unuploadedRidesAcknowledged: true
                    )
                }
            }
        }
        supportAction
    }

    @ViewBuilder
    private func trackingContent(_ status: AccountDeletionStatus) -> some View {
        let remedies = AccountDeletionPresentation.remedies(for: status.blockers)
        statusCard(
            label: AccountDeletionPresentation.statusLabel(status),
            showsProgress: AccountDeletionPresentation.showsProgress(status)
        )
        if !status.blockers.isEmpty {
            SectionHeader(title: "Blocked")
                .padding(.top, 26)
            GroupCard { forEachBlocker(status.blockers) }
        }
        if status.failureCode != nil {
            SectionHeader(title: "Previous Attempt")
                .padding(.top, 26)
            GroupCard {
                GrammarRow(
                    label: AccountDeletionPresentation.failureLabel(status.failureCode)
                )
            }
        }
        switch status.status {
        case .blocked:
            if remedies.contains(.reviewSettlements) {
                actionCard(label: "Review Settlements") { showSettlements = true }
            }
            if remedies.contains(.openBalance) {
                actionCard(label: "Open Balance") {
                    openURL(AppConfig.portalBalanceURL)
                }
            }
            if status.retryable,
               !remedies.contains(.contactSupport) {
                actionCard(label: "Retry") { Task { await model.retry() } }
            }
            if !status.retryable
                || remedies.contains(.contactSupport) {
                supportAction
            }
            diagnosticsAction
        case .failedRetryable:
            if status.retryable {
                actionCard(label: "Try Again") { Task { await model.retry() } }
            }
        case .needsSupport, .legacyUnverified:
            if model.canDiscardSavedStatus { discardAction }
            supportAction
            diagnosticsAction
        case .queued, .processing, .completed:
            EmptyView()
        }
    }

    private func statusCard(label: String, showsProgress: Bool = false) -> some View {
        GroupCard {
            HStack(spacing: 10) {
                if showsProgress {
                    ProgressView()
                        .controlSize(.small)
                        .tint(Theme.gray)
                        .accessibilityHidden(true)
                }
                Text(label)
                    .font(.body)
                    .foregroundStyle(Theme.ink)
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 14)
            .frame(minHeight: Theme.row)
            .accessibilityElement(children: .combine)
            .accessibilityLabel(label)
        }
    }

    private func actionCard(label: String, action: @escaping () -> Void) -> some View {
        GroupCard { CenteredActionRow(label: label, action: action) }
            .padding(.top, 20)
    }

    private var diagnosticsAction: some View {
        actionCard(label: "Diagnostics") { showDiagnostics = true }
    }

    private var supportAction: some View {
        actionCard(label: "Contact Support") {
            openURL(AppConfig.supportURL)
        }
    }

    private var discardAction: some View {
        actionCard(label: "Remove Saved Status") {
            Task { await model.discardSavedStatus() }
        }
    }

    @ViewBuilder
    private func forEachBlocker(_ blockers: [AccountDeletionBlocker]) -> some View {
        ForEach(Array(blockers.enumerated()), id: \.offset) { index, blocker in
            if index > 0 { RowSeparator() }
            GrammarRow(
                label: AccountDeletionPresentation.blockerLabel(blocker),
                value: blocker.count.map(String.init)
            )
        }
    }

    private func preflightLabel(_ preflight: AccountDeletionPreflight) -> String {
        if !preflight.available { return "Unavailable" }
        if preflight.isAuthoritativeReady { return "Ready" }
        return preflight.isAvailableToFile ? "Ready to File" : "Blocked"
    }

    private func rideTitle(_ ride: AccountDeletionLocalRide) -> String {
        Format.displayRideTitle(
            nil,
            startedAtISO: Format.isoParser.string(from: ride.startedAt),
            placeLabel: nil
        )
    }

    private var readyInventoryDigest: String? {
        switch model.state {
        case let .ready(_, inventory), let .retryReview(_, inventory):
            return inventory.digest
        default:
            return nil
        }
    }

    private var readyInventoryHasRides: Bool {
        switch model.state {
        case let .ready(_, inventory), let .retryReview(_, inventory):
            return !inventory.rides.isEmpty
        default:
            return false
        }
    }

    private var pollingID: String? {
        guard scenePhase == .active,
              case let .tracking(status) = model.state,
              AccountDeletionPresentation.pollsAutomatically(status)
        else { return nil }
        return "\(status.requestID):\(status.updatedAt ?? ""):\(model.pollFailureCount)"
    }

    private var isWorking: Bool {
        switch model.state {
        case .loading, .requesting, .clearingLocalData: return true
        case .ready, .retryReview, .tracking, .requestNotFound, .statusUnavailable,
             .storageUnavailable, .ownerMismatch, .supportRequired, .localCleanupFailed,
             .completed, .completedLocally, .discarded:
            return false
        }
    }

    private var isCompleted: Bool {
        switch model.state {
        case .completed, .completedLocally:
            return true
        default:
            return false
        }
    }
}

/// Recovery surface for deletion-specific authentication refusals that arrive
/// without this device's status capability (for example, a request filed in
/// the portal). It preserves and inventories local ride custody; no local
/// source is removed from this route without the separate N14 confirmation.
struct AccountDeletionSessionView: View {
    private enum InventoryState: Equatable {
        case loading
        case available(AccountDeletionLocalInventory)
        case unavailable
    }

    @Environment(AppSession.self) private var session
    @Environment(\.openURL) private var openURL

    let record: AccountDeletionSessionRecord

    @State private var inventoryState: InventoryState = .loading
    @State private var showDiagnostics = false
    @State private var reviewedRecordings = false
    @State private var confirmingLocalCleanup = false
    @State private var isClearingLocalData = false
    @State private var localCleanupFailed = false

    var body: some View {
        ZStack {
            Theme.sheet.ignoresSafeArea()
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    SheetHeader(
                        title: "Account Deletion",
                        doneEnabled: AccountDeletionHeaderPolicy.recoveryDoneEnabled(
                            record: record
                        )
                    ) {
                        try? session.acknowledgeAccountDeletionSessionCompletion()
                    }
                        .padding(.top, 6)
                    VStack(alignment: .leading, spacing: 0) {
                        statusCard
                        if record.localCleanupCompletedAt == nil {
                            inventoryContent
                            if canOfferLocalCleanup {
                                actionCard(label: "Clear Local Data") {
                                    confirmingLocalCleanup = true
                                }
                            }
                            if record.state != .deleted {
                                actionCard(label: "Try Sign In") {
                                    try? session.prepareToReauthenticateAfterAccountDeletionState()
                                }
                            }
                        }
                        actionCard(label: "Contact Support") {
                            openURL(AppConfig.supportURL)
                        }
                        actionCard(label: "Diagnostics") {
                            showDiagnostics = true
                        }
                    }
                    .padding(.horizontal, Theme.margin)
                    .padding(.top, 22)
                    .padding(.bottom, 32)
                }
            }
        }
        .task(id: record) { await loadInventory() }
        .confirmationDialog(
            "Clear Local Data?",
            isPresented: $confirmingLocalCleanup,
            titleVisibility: .visible
        ) {
            Button("Clear Local Data", role: .destructive) {
                Task { await clearLocalData() }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            if case let .available(inventory) = inventoryState,
               !inventory.rides.isEmpty,
               let removalConsent = AccountDeletionConsentCopy.unuploadedRideRemoval {
                Text(removalConsent)
            }
        }
        .sheet(isPresented: $showDiagnostics) {
            DiagnosticsSheet()
                .presentationCornerRadius(Theme.crown)
        }
        .interactiveDismissDisabled()
    }

    private var statusCard: some View {
        let label: String
        if isClearingLocalData {
            label = "Clearing Local Data"
        } else if localCleanupFailed {
            label = "Local Cleanup Failed"
        } else if record.savedStatusRemoved {
            label = "Saved Status Removed"
        } else {
            switch record.state {
            case .pending: label = "In Progress"
            case .deleted: label = "Completed"
            case .identityUnavailable: label = "Needs Support"
            }
        }
        return GroupCard {
            GrammarRow(label: "Status", value: label)
        }
    }

    @ViewBuilder
    private var inventoryContent: some View {
        SectionHeader(title: "Ride Recordings")
            .padding(.top, 26)
        GroupCard {
            switch inventoryState {
            case .loading:
                HStack(spacing: 10) {
                    ProgressView()
                        .controlSize(.small)
                        .tint(Theme.gray)
                    Text("Checking")
                        .foregroundStyle(Theme.ink)
                    Spacer(minLength: 0)
                }
                .padding(.horizontal, 14)
                .frame(minHeight: Theme.row)
            case .unavailable:
                GrammarRow(label: "Local Inventory", value: "Unavailable")
            case let .available(inventory):
                if inventory.rides.isEmpty {
                    GrammarRow(label: "Unuploaded Rides", value: "None")
                } else {
                    ForEach(Array(inventory.rides.enumerated()), id: \.element.id) { index, ride in
                        if index > 0 { RowSeparator() }
                        GrammarRow(label: rideTitle(ride), value: "Unuploaded")
                    }
                    RowSeparator(inset: 0)
                    GrammarRow(
                        label: "Ride Recordings Reviewed",
                        trailingSystemImage: reviewedRecordings ? "checkmark" : nil
                    ) {
                        reviewedRecordings.toggle()
                    }
                    if AccountDeletionConsentCopy.unuploadedRideRemoval == nil {
                        RowSeparator(inset: 0)
                        GrammarRow(label: "Removal Confirmation", value: "Pending")
                    }
                }
            }
        }
        if case .unavailable = inventoryState {
            actionCard(label: "Try Again") {
                Task { await loadInventory() }
            }
        }
    }

    private func loadInventory() async {
        guard record.localCleanupCompletedAt == nil else { return }
        inventoryState = .loading
        reviewedRecordings = false
        localCleanupFailed = false
        do {
            inventoryState = .available(
                try await session.accountDeletionSessionInventory(
                    recoveryID: record.recoveryID
                )
            )
        } catch {
            inventoryState = .unavailable
        }
    }

    private var canOfferLocalCleanup: Bool {
        guard record.state == .deleted,
              !isClearingLocalData,
              case let .available(inventory) = inventoryState
        else { return false }
        if inventory.rides.isEmpty { return true }
        return AccountDeletionConsentCopy.acknowledgesRemoval(
            of: inventory,
            reviewed: reviewedRecordings
        )
    }

    private func clearLocalData() async {
        guard case let .available(inventory) = inventoryState,
              inventory.rides.isEmpty
                || AccountDeletionConsentCopy.acknowledgesRemoval(
                    of: inventory,
                    reviewed: reviewedRecordings
                )
        else { return }
        isClearingLocalData = true
        localCleanupFailed = false
        do {
            try await session.completeLocalAccountDeletionFromSessionRecord(
                recoveryID: record.recoveryID,
                reviewedInventoryDigest: inventory.digest,
                unuploadedRidesAcknowledged: true
            )
        } catch {
            // Cleanup is an idempotent saga: an early owner-bound purge may
            // have succeeded before a later store failed. Never leave the old
            // inventory digest/review armed as an apparent retry. Re-read the
            // exact remaining custody and require a fresh acknowledgement.
            reviewedRecordings = false
            do {
                inventoryState = .available(
                    try await session.accountDeletionSessionInventory(
                        recoveryID: record.recoveryID
                    )
                )
            } catch {
                inventoryState = .unavailable
            }
            localCleanupFailed = true
        }
        isClearingLocalData = false
    }

    private func actionCard(label: String, action: @escaping () -> Void) -> some View {
        GroupCard { CenteredActionRow(label: label, action: action) }
            .padding(.top, 20)
    }

    private func rideTitle(_ ride: AccountDeletionLocalRide) -> String {
        Format.displayRideTitle(
            nil,
            startedAtISO: Format.isoParser.string(from: ride.startedAt),
            placeLabel: nil
        )
    }
}
