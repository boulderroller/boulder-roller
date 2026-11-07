import SwiftUI

@main
struct BoulderRollerApp: App {
    @UIApplicationDelegateAdaptor(RideUploadApplicationDelegate.self)
    private var rideUploadDelegate
    @State private var session = AppSession()

    init() {
        // MetricKit crash/hang diagnostics — subscribe at launch so the
        // OS delivers anything captured since the previous run.
        CrashReporting.start()
        // Bound the on-disk map snapshot layer once per launch, off-main.
        Task.detached(priority: .utility) { RouteMapSnapshot.SnapshotDisk.prune() }
    }

    #if DEBUG
    private let powerRenderFixture = PowerRenderFixtureMode(
        arguments: ProcessInfo.processInfo.arguments
    )
    private let balanceRenderFixture = BalanceRenderFixtureMode(
        arguments: ProcessInfo.processInfo.arguments
    )
    private let rideUploadRenderFixture = RideUploadRenderFixtureMode(
        arguments: ProcessInfo.processInfo.arguments
    )
    private let recordingRecoveryRenderFixture = RecordingRecoveryRenderFixtureMode(
        arguments: ProcessInfo.processInfo.arguments
    )
    private let physiologyRenderFixture = PhysiologyRenderFixtureMode(
        arguments: ProcessInfo.processInfo.arguments
    )
    private let thresholdRenderFixture = ThresholdRenderFixtureMode(
        arguments: ProcessInfo.processInfo.arguments
    )
    private let sensorQualityRenderFixture = SensorQualityRenderFixtureMode(
        arguments: ProcessInfo.processInfo.arguments
    )
    private let routeRenderFixture = RouteRenderFixtureMode(
        arguments: ProcessInfo.processInfo.arguments
    )
    private let recordingLayoutRenderFixture = RecordingLayoutRenderFixtureMode(
        arguments: ProcessInfo.processInfo.arguments
    )
    private let ridePublicationReviewRenderFixture = RidePublicationReviewRenderFixtureMode(
        arguments: ProcessInfo.processInfo.arguments
    )
    private let rideDetailRenderFixture = RideDetailRenderFixtureMode(
        arguments: ProcessInfo.processInfo.arguments
    )
    private let climbProfileRenderFixture = ClimbProfileRenderFixtureMode(
        arguments: ProcessInfo.processInfo.arguments
    )
    #endif

    var body: some Scene {
        WindowGroup {
            Group {
            #if DEBUG
            if let powerRenderFixture {
                PowerRenderFixtureRoot(mode: powerRenderFixture)
                    .preferredColorScheme(.dark)
            } else if let stage1Fixture = Stage1RenderFixtureMode.current {
                Stage1RenderFixtureRoot(mode: stage1Fixture)
                    .preferredColorScheme(.dark)
            } else if ProcessInfo.processInfo.arguments.contains("-BREstimateCopyRenderFixture") {
                EstimateCopyRenderFixtureRoot()
                    .preferredColorScheme(.dark)
            } else if let climbProfileRenderFixture {
                ClimbProfileRenderFixtureRoot(mode: climbProfileRenderFixture)
                    .preferredColorScheme(.dark)
                    .background(Theme.screen)
            } else if let balanceRenderFixture {
                BalanceRenderFixtureRoot(mode: balanceRenderFixture)
                    .preferredColorScheme(.dark)
                    .background(Theme.screen)
            } else if let rideUploadRenderFixture {
                RideUploadRenderFixtureRoot(mode: rideUploadRenderFixture)
                    .preferredColorScheme(.dark)
                    .background(Theme.screen)
            } else if let recordingRecoveryRenderFixture {
                RecordingRecoveryRenderFixtureRoot(mode: recordingRecoveryRenderFixture)
                    .preferredColorScheme(.dark)
                    .background(Theme.screen)
            } else if let physiologyRenderFixture {
                PhysiologyRenderFixtureRoot(mode: physiologyRenderFixture)
                    .preferredColorScheme(.dark)
                    .background(Theme.screen)
            } else if let thresholdRenderFixture {
                ThresholdRenderFixtureRoot(mode: thresholdRenderFixture)
                    .preferredColorScheme(.dark)
                    .background(Theme.screen)
            } else if let sensorQualityRenderFixture {
                SensorQualityRenderFixtureRoot(mode: sensorQualityRenderFixture)
                    .preferredColorScheme(.dark)
                    .background(Theme.screen)
            } else if let routeRenderFixture {
                RouteRenderFixtureRoot(mode: routeRenderFixture)
                    .preferredColorScheme(.dark)
                    .background(Theme.screen)
            } else if let recordingLayoutRenderFixture {
                RecordingLayoutRenderFixtureRoot(mode: recordingLayoutRenderFixture)
                    .preferredColorScheme(.dark)
                    .background(Theme.screen)
            } else if let ridePublicationReviewRenderFixture {
                RidePublicationReviewRenderFixtureRoot(mode: ridePublicationReviewRenderFixture)
                    .preferredColorScheme(.dark)
                    .background(Theme.screen)
            } else if let rideDetailRenderFixture {
                RideDetailRenderFixtureRoot(mode: rideDetailRenderFixture)
                    .preferredColorScheme(ProcessInfo.processInfo.arguments.contains("-BRRenderLight") ? .light : .dark)
                    .background(Theme.screen)
            } else {
                productionRoot
            }
            #else
            productionRoot
            #endif
            }
            // One action blue for system controls too (pickers, links, share).
            .tint(Theme.blue)
        }
    }

    private var productionRoot: some View {
        RootView()
            .environment(session)
            .environment(\.units, UnitSystem(preferredUnits: session.currentUser?.preferredUnits))
            .preferredColorScheme(.dark)   // fixed dark ramp (color ledger)
            .background(Theme.screen)
            .onOpenURL { url in
                // Share-sheet / Files "Open in Boulder Roller" entry —
                // joins the same import pipeline.
                let owner = session.currentUser.map { RecordingOwner(user: $0) }
                guard AccountDeletionLocalFence.permitsAccountWork(owner: owner) else { return }
                if ["gpx", "fit", "tcx"].contains(url.pathExtension.lowercased()) {
                    session.pendingImportURL = url
                }
            }
    }
}

enum AccountDeletionRootDestination: Equatable {
    case lifecycle
    case deletionSession
    case account

    static func resolve(
        storage: AccountDeletionCapabilityStorageState,
        sessionRecord: AccountDeletionSessionRecord?,
        signedInOwner: RecordingOwner?,
        reauthenticationRequested: Bool = false
    ) -> Self {
        func belongsToSignedInOwner(_ capability: AccountDeletionCapability) -> Bool {
            guard let signedInOwner, let capabilityOwner = capability.owner else {
                return true
            }
            return signedInOwner == capabilityOwner
        }

        func recordBelongsToSignedInOwner(_ record: AccountDeletionSessionRecord) -> Bool {
            guard let signedInOwner, let recordOwner = record.owner else {
                return true
            }
            return signedInOwner == recordOwner
        }

        switch storage {
        case .unavailable:
            return .lifecycle
        case let .available(capability):
            return belongsToSignedInOwner(capability) ? .lifecycle : .account
        case let .unconfirmed(capability):
            guard belongsToSignedInOwner(capability), let sessionRecord else {
                return .account
            }
            guard let capabilityOwner = capability.owner,
                  let recordOwner = sessionRecord.owner
            else { return .lifecycle }
            return capabilityOwner == recordOwner ? .lifecycle : .account
        case .none:
            guard let sessionRecord else { return .account }
            if reauthenticationRequested { return .account }
            return recordBelongsToSignedInOwner(sessionRecord) ? .deletionSession : .account
        }
    }
}

enum AccountDeletionForegroundRecovery {
    static func shouldReload(storage: AccountDeletionCapabilityStorageState) -> Bool {
        if case .unavailable = storage { return true }
        return false
    }
}

struct RootView: View {
    @Environment(AppSession.self) private var session
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        @Bindable var session = session
        ZStack {
            Theme.screen.ignoresSafeArea()
            switch AccountDeletionRootDestination.resolve(
                storage: session.accountDeletionCapabilityState,
                sessionRecord: session.accountDeletionSessionRecord,
                signedInOwner: session.accountRoutingOwner,
                reauthenticationRequested: session.accountDeletionReauthenticationRequested
            ) {
            case .lifecycle:
                AccountDeletionRoomView(allowsDismiss: false)
            case .deletionSession:
                if let deletionRecord = session.accountDeletionSessionRecord {
                    AccountDeletionSessionRoomView(record: deletionRecord)
                }
            case .account:
                switch session.phase {
                case .resuming:
                    ProgressView()
                        .tint(Theme.gray)
                case .signedOut:
                    OnboardingView()
                case .signedIn:
                    FeedView()
                }
            }
        }
        .fullScreenCover(item: $session.pendingImportURL) { url in
            ImportFlowView(fileURL: url)
        }
        .fullScreenCover(item: $session.pendingInterruptedRide) { recovery in
            InterruptedRideRecoveryView(
                recovery: recovery,
                discardIntentPending: session.interruptedRideActionIntent == .discard,
                onSave: { try await session.saveInterruptedRide(recovery) },
                onDiscard: { try await session.discardInterruptedRide(recovery) }
            )
        }
        .fullScreenCover(item: $session.pendingRidePrivacyReview) { job in
            RidePublicationReviewView(
                job: job,
                onSave: { settings, draft, photoBytes in
                    try await session.approveRidePublication(
                        job,
                        settings: settings,
                        draft: draft,
                        photoBytes: photoBytes
                    )
                },
                onLater: { session.deferRidePrivacyReview(job) }
            )
        }
        .fullScreenCover(item: $session.pendingRideReveal) { pending in
            FinishedRidePresentation(pending: pending)
                .interactiveDismissDisabled()
        }

        .sheet(item: $session.pendingFinishedRideID) { rideID in
            // Ceremony handoff stays modal; the wrapper supplies the stack
            // and the Done the pushed detail no longer carries.
            NavigationStack {
                RideDetailView(rideId: rideID)
                    .toolbar {
                        ToolbarItem(placement: .topBarLeading) {
                            Button("Done") { session.pendingFinishedRideID = nil }
                        }
                    }
            }
            .presentationCornerRadius(Theme.crown)
        }
        // The custody-unavailable state renders as a quiet inline card with
        // Retry at the top of the feed (bead c6l2l item 7) — no modal, no
        // sign-out remedy here; sign-out lives in the avatar sheet.
        .task {
            guard AccountDeletionRootDestination.resolve(
                storage: session.accountDeletionCapabilityState,
                sessionRecord: session.accountDeletionSessionRecord,
                signedInOwner: session.accountRoutingOwner,
                reauthenticationRequested: session.accountDeletionReauthenticationRequested
            ) == .account else { return }
            await session.resume()
        }
        .onChange(of: scenePhase) { _, phase in
            guard phase == .active else { return }
            session.invalidateRiderThresholdAuthority()
            Task {
                if AccountDeletionForegroundRecovery.shouldReload(
                    storage: session.accountDeletionCapabilityState
                ) {
                    await session.reloadAccountDeletionStorage()
                    return
                }
                guard AccountDeletionRootDestination.resolve(
                    storage: session.accountDeletionCapabilityState,
                    sessionRecord: session.accountDeletionSessionRecord,
                    signedInOwner: session.accountRoutingOwner,
                    reauthenticationRequested: session.accountDeletionReauthenticationRequested
                ) == .account else { return }
                // A degraded (offline-resumed) session retries quietly on
                // every foreground; success drops the banner.
                await session.revalidateIfDegraded()
                await session.refreshRiderThresholdAuthority()
                await session.refreshRideUploads()
            }
            // Foreground is also the drain opportunity for any queued
            // crash diagnostics (quiet no-op signed out or offline).
            CrashReporting.drainQueue()
        }
    }
}

extension URL: @retroactive Identifiable {
    public var id: String { absoluteString }
}
