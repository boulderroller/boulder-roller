import MapKit
import SwiftUI

private struct FeedRideDestination: Identifiable, Hashable {
    let id: String
}

private struct FeedLoadIdentity: Hashable {
    let owner: RecordingOwner?
    let scope: FeedScope
}

/// Surface 2 — Feed: the app's one screen. Rides only, chronological.
/// Feed whispers (Law 2): names carry the flavor, one CAL figure, the avatar
/// dot is the settlement announcement.
struct FeedView: View {
    @Environment(AppSession.self) private var session
    @State private var model: FeedModel
    @State private var showAvatarSheet = false
    @State private var showRecording = false
    @State private var selectedRide: FeedRideDestination?
    @State private var selectedLocalRide: LocalSavedRide?
    /// One feed for now — global, chronological (Tim, 2026-08-17).
    /// Following may return when the cohort outgrows a single room.
    private let selectedScope = FeedScope.global
    /// Notification tap destinations, consumed from the router exactly once
    /// (Law 7: pushes deep-link to surfaces; no notification room). A climb
    /// pushes onto the content spine; settlements opens its room sheet.
    @State private var pushedClimbId: String?
    @State private var showCanonMap = false
    @State private var showSettlementsFromPush: PushDeepLink?

    init() {
        _model = State(initialValue: FeedModel())
    }

    private var owner: RecordingOwner? {
        session.currentUser.map(RecordingOwner.init(user:))
    }

    /// Anticipation: the ride pages a rider is likeliest to open next get
    /// their small reads (detail + climbs, never gps/streams) warmed so the
    /// first tap paints from cache (grout pass, 2026-08-21).
    private func warmTopRides() {
        let ids: [String] = model.items.prefix(4).compactMap { item in
            switch item.source {
            case let .server(ride): return ride.id
            case let .activity(activity): return activity.rideID
            case .local: return nil
            }
        }
        guard !ids.isEmpty else { return }
        Task.detached(priority: .utility) {
            for id in ids {
                _ = try? await APIClient.shared.rideDetail(id: id)
                _ = try? await APIClient.shared.ridePatterns(id: id)
            }
        }
    }

    private var displayedItems: [FeedDisplayItem] {
        guard let owner,
              model.loadedOwner == owner,
              model.loadedScope == selectedScope
        else { return [] }
        return FeedDisplayAssembler.merge(
            localSavedRides: session.localSavedRides ?? [],
            items: model.items
        )
    }

    #if DEBUG
    /// Release-impossible render seam. The launch fixture supplies durable-job
    /// projections while this production view and its real cards do the draw.
    init(debugItems: [RideFeedItem], owner: RecordingOwner) {
        _model = State(initialValue: FeedModel(debugItems: debugItems, owner: owner))
    }
    #endif

    var body: some View {
        NavigationStack {
            feedBody
        }
    }

    /// The content spine: feed is the root; ride, climb, local ride push
    /// with back edges. Sheets remain for rooms (avatar) and ceremonies.
    private var feedBody: some View {
        ZStack(alignment: .bottom) {
            Theme.screen.ignoresSafeArea()

            ScrollView {
                LazyVStack(spacing: 12) {
                    // Local custody unavailable: a quiet inline state, not a
                    // modal — Retry is the only remedy here (sign-out stays
                    // where it lives, in the avatar sheet).
                    if session.interruptedRideErrorMessage != nil {
                        CustodyUnavailableCard {
                            Task { await session.retryInterruptedRideRecovery() }
                        }
                    }
                    // Degraded resume (server unreachable at launch): the
                    // rider is on this device's copy. One quiet truthful
                    // line — never a wall, never a sign-out (bead f4acp.2.9).
                    if session.connectivity == .unreachable {
                        OfflineResumeCard {
                            Task { await session.revalidateIfDegraded() }
                        }
                    }
                    if model.isShowingCachedData {
                        CachedFeedCard {
                            Task { await model.reload(owner: owner, scope: selectedScope) }
                        }
                    }
                    ForEach(Array(displayedItems.enumerated()), id: \.element.id) { index, item in
                        feedCard(for: item)
                            .onAppear {
                                // Anticipation: fetch the next page while the
                                // rider is still four cards from the end, not
                                // when the spinner scrolls into view.
                                if index >= displayedItems.count - 4 {
                                    Task { await model.loadNextPage(owner: owner, scope: selectedScope) }
                                }
                            }
                    }

                    // An empty feed serves no object (Tim, 2026-08-17) —
                    // the record pill is the whole invitation. Only genuine
                    // unavailability gets a card.
                    if displayedItems.isEmpty,
                       model.loadFailed,
                       model.loadedOwner == owner,
                       model.loadedScope == selectedScope
                    {
                        FeedUnavailableState {
                            Task { await model.reload(owner: owner, scope: selectedScope) }
                        }
                    }

                    if model.paginationFailed {
                        Button("Try loading more again") {
                            Task {
                                await model.loadNextPage(owner: owner, scope: selectedScope)
                            }
                        }
                        .font(.footnote.weight(.medium))
                        .foregroundStyle(Theme.gray)
                        .frame(minHeight: 44)
                    } else if model.hasMore, let cursor = model.nextCursor {
                        ProgressView()
                            .tint(Theme.gray)
                            .frame(minHeight: 44)
                            .task(id: cursor) {
                                await model.loadNextPage(owner: owner, scope: selectedScope)
                            }
                            .accessibilityLabel("Loading more rides")
                    }
                }
                .padding(.horizontal, Theme.margin)
                .padding(.bottom, 90)
            }
            .scrollEdgeEffectStyle(.soft, for: .top)
            .refreshable {
                guard !model.usesFixture else { return }
                await model.reload(owner: owner, scope: selectedScope)
            }

            recordPill
        }
        // The platform bar treatment (iOS 26): safeAreaBar + the scroll
        // view's soft top edge effect keep the wordmark legible over bright
        // map content without putting material on the content layer. The
        // system navigation bar stays hidden on the root; pushed views
        // bring their own.
        .toolbar(.hidden, for: .navigationBar)
        .safeAreaBar(edge: .top, spacing: 0) { topBar }
        .sheet(isPresented: $showAvatarSheet) {
            AvatarSheet()
                .presentationCornerRadius(Theme.crown)
        }
        .navigationDestination(item: $selectedRide) { destination in
            RideDetailView(rideId: destination.id)
        }
        .navigationDestination(item: $selectedLocalRide) { ride in
            LocalRideView(ride: ride)
        }
        .navigationDestination(item: $pushedClimbId) { climbId in
            ClimbDetailView(climbId: climbId)
        }
        .navigationDestination(isPresented: $showCanonMap) {
            CanonMapView()
        }
        .fullScreenCover(isPresented: $showRecording) {
            if let user = session.currentUser {
                RecordingView(user: user)
            }
        }
        .sheet(item: $showSettlementsFromPush) { _ in
            SettlementsView()
                .presentationCornerRadius(Theme.crown)
        }
        .task(id: FeedLoadIdentity(owner: owner, scope: selectedScope)) {
            guard !model.usesFixture else { return }
            await model.reload(owner: owner, scope: selectedScope)
            warmTopRides()
            await session.refreshBalanceActions()
            await session.refreshSettlementDot()
            // Token-rotation replay for riders who already granted
            // notifications; never a first ask (PushAskPolicy).
            PushRegistrar.registerIfPreviouslyAuthorized()
            consumePendingPushLink()
        }
        .onChange(of: PushRouter.shared.pending) {
            consumePendingPushLink()
        }
        .onChange(of: session.lastImportCompletedAt) {
            Task {
                guard !model.usesFixture else { return }
                await model.reload(owner: owner, scope: selectedScope)
                await session.refreshSettlementDot()
            }
        }
    }

    /// Move the routed deep link into this feed's presentation, once.
    private func consumePendingPushLink() {
        guard !model.usesFixture, let link = PushRouter.shared.pending else { return }
        PushRouter.shared.pending = nil
        switch link {
        case .settlements:
            showSettlementsFromPush = link
        case let .climb(climbId):
            pushedClimbId = climbId
        }
    }

    @ViewBuilder
    private func feedCard(for item: FeedDisplayItem) -> some View {
        switch item.source {
        case let .localSaved(ride):
            // The card is the tap (§4): local evidence opens its own local
            // surface — never a pretend server ride.
            Button {
                selectedLocalRide = ride
            } label: {
                LocalSavedRideCard(
                    ride: ride,
                    riderName: session.currentUser?.shownName
                )
            }
            .buttonStyle(.plain)
        case let .existing(item):
            existingFeedCard(for: item)
        }
    }

    @ViewBuilder
    private func existingFeedCard(for item: RideFeedItem) -> some View {
        switch item.source {
        case let .server(ride):
            Button {
                selectedRide = FeedRideDestination(id: ride.id)
            } label: {
                RideCard(
                    ride: ride,
                    riderName: session.currentUser?.shownName,
                    climbSummary: model.climbSummaries[ride.id]
                )
            }
            .buttonStyle(.plain)
            .task { await model.loadClimbSummary(for: ride) }
        case let .activity(activity):
            if let rideID = activity.rideID {
                Button {
                    selectedRide = FeedRideDestination(id: rideID)
                } label: {
                    FeedActivityCard(
                        activity: activity,
                        isOwnRide: activity.rider?.id != nil
                            && activity.rider?.id == session.currentUser?.id
                    )
                }
                .buttonStyle(.plain)
            }
        case let .local(job):
            // A persisted local upload remains a status card until the
            // authoritative ride is final. It is deliberately not a button:
            // nonfinal work must not open as though a server ride exists.
            LocalRideCard(
                job: job,
                riderName: session.currentUser?.shownName,
                onReview: job.phase == .awaitingPrivacyReview ? {
                    session.presentRidePrivacyReview(job)
                } : nil,
                onRetry: job.canRetry ? {
                    guard !model.usesFixture, let owner else { return }
                    Task {
                        await RideUploadRuntime.shared.retry(jobID: job.id, owner: owner)
                        await model.reload(owner: owner, scope: selectedScope)
                    }
                } : nil
            )
        }
    }

    private var topBar: some View {
        HStack {
            Text("Boulder Roller")
                .font(.subheadline.weight(.semibold))
                .kerning(-0.2)
                .foregroundStyle(Theme.ink)
            Spacer()
            // The canon, one tap from home (Tim un-deferred the map
            // 2026-08-18). Gray glyph: navigation, not action.
            Button {
                showCanonMap = true
            } label: {
                Image(systemName: "map")
                    .font(.subheadline)
                    .foregroundStyle(Theme.gray)
                    .frame(width: 32, height: 32)
                    .contentShape(Circle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Climbs map")
            .padding(.trailing, 2)
            Button {
                showAvatarSheet = true
            } label: {
                ZStack(alignment: .topTrailing) {
                    AvatarView(name: session.currentUser?.shownName, size: 28)
                        .overlay(Circle().stroke(.white.opacity(0.12), lineWidth: 0.5))
                    if session.hasUncollectedSettlements == true {
                        Circle()
                            .fill(Theme.blue)
                            .frame(width: 9, height: 9)
                            .overlay(Circle().stroke(Theme.screen, lineWidth: 2))
                            .offset(x: 2, y: -2)
                    }
                }
            }
            .buttonStyle(.plain)
            .accessibilityLabel(
                session.hasUncollectedSettlements == true
                    ? "Your profile, settlements ready"
                    : "Your profile"
            )
        }
        .padding(.horizontal, Theme.margin)
        .padding(.vertical, 10)
        // Chrome, not content: the bar itself stays transparent — the
        // ScrollView's soft top scroll-edge effect (the platform's iOS 26
        // toolbar treatment) does the legibility work under it.
    }

    /// The glass record pill — the feed's one blue action (Record owns the
    /// feed), floating bottom-center on the chrome layer. Liquid Glass via
    /// the platform's glassEffect; glass is strictly chrome, never content.
    private var recordPill: some View {
        Button {
            showRecording = true
        } label: {
            HStack(spacing: 8) {
                Circle().fill(Theme.blue).frame(width: 9, height: 9)
                Text("Record")
                    .font(.subheadline.weight(.medium))
                    .foregroundStyle(Theme.ink)
            }
            .padding(.horizontal, 22)
            .padding(.vertical, 11)
            .glassEffect(.regular.interactive(), in: .capsule)
        }
        .buttonStyle(.plain)
        // Floating chrome stays compact enough not to cover an entire card at
        // accessibility sizes; the control retains its VoiceOver label and a
        // comfortably larger-than-44-point hit target.
        .dynamicTypeSize(...DynamicTypeSize.xxxLarge)
        .padding(.bottom, 16)
        .accessibilityLabel("Record")
    }
}

/// Item 7 (bead c6l2l): the fail-closed "Ride evidence is unavailable"
/// dialog demoted to an inline quiet state. Retry is the one remedy; the
/// state clears itself the moment custody probing succeeds.
/// Offline-resume banner: same quiet inline species as the custody card.
/// States the fact and offers the retry; everything below it keeps working
/// on this device's copy.
private struct OfflineResumeCard: View {
    let onRetry: () -> Void

    var body: some View {
        HStack(spacing: 12) {
            Text("Offline. Showing what's stored on this phone.")
                .font(.footnote)
                .foregroundStyle(Theme.gray)
            Spacer(minLength: 8)
            Button("Retry", action: onRetry)
                .font(.footnote.weight(.medium))
                .foregroundStyle(Theme.gray)
                .buttonStyle(.plain)
                .frame(minHeight: 44)
        }
        .padding(.horizontal, 14)
        .frame(minHeight: Theme.row)
        .background(Theme.feedCard)
        .overlay(
            RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous)
                .stroke(.white.opacity(0.06), lineWidth: 0.5)
        )
        .clipShape(RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous))
    }
}

private struct CustodyUnavailableCard: View {
    let onRetry: () -> Void

    var body: some View {
        HStack(spacing: 12) {
            Text("Ride evidence is unavailable")
                .font(.footnote)
                .foregroundStyle(Theme.gray)
            Spacer(minLength: 8)
            Button("Retry", action: onRetry)
                .font(.footnote.weight(.medium))
                .foregroundStyle(Theme.gray)
                .buttonStyle(.plain)
                .frame(minHeight: 44)
        }
        .padding(.horizontal, 14)
        .frame(minHeight: Theme.row)
        .background(Theme.feedCard)
        .overlay(
            RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous)
                .stroke(.white.opacity(0.06), lineWidth: 0.5)
        )
        .clipShape(RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous))
    }
}

private struct CachedFeedCard: View {
    let onRetry: () -> Void

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: "wifi.slash")
                .foregroundStyle(Theme.gray)
                .accessibilityHidden(true)
            Text("Showing saved rides")
                .font(.footnote)
                .foregroundStyle(Theme.gray)
            Spacer(minLength: 8)
            Button("Refresh", action: onRetry)
                .font(.footnote.weight(.medium))
                .foregroundStyle(Theme.gray)
                .buttonStyle(.plain)
                .frame(minHeight: 44)
        }
        .padding(.horizontal, 14)
        .background(Theme.feedCard)
        .clipShape(RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous))
    }
}

/// Unavailability speaks in the same quiet inline species as the custody
/// and offline cards — never stock empty-state furniture.
private struct FeedUnavailableState: View {
    let onRetry: () -> Void

    var body: some View {
        HStack(spacing: 12) {
            Text("Rides are unavailable")
                .font(.footnote)
                .foregroundStyle(Theme.gray)
            Spacer(minLength: 8)
            Button("Retry", action: onRetry)
                .font(.footnote.weight(.medium))
                .foregroundStyle(Theme.gray)
                .buttonStyle(.plain)
                .frame(minHeight: 44)
        }
        .padding(.horizontal, 14)
        .frame(minHeight: Theme.row)
        .background(Theme.feedCard)
        .overlay(
            RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous)
                .stroke(.white.opacity(0.06), lineWidth: 0.5)
        )
        .clipShape(RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous))
    }
}

/// The feed-card stat cell: a plain Apple-style label and value. Position and
/// units carry meaning without ornamental x/y/z markers.
struct FeedCardStat: View {
    let label: String
    let value: String
    var unit: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 1) {
            Text(label)
                .font(.caption2)
                .foregroundStyle(Theme.gray)
            // An abstaining value carries no unit: the dash stands alone.
            StatValueText(value: value, unit: value == "—" ? nil : unit, valueFont: .numeral(.subheadline))
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(label) \(value) \(value == "—" ? "" : (unit ?? ""))")
    }
}

/// One stat-trio grammar for every feed card variant.
struct FeedCardStatTrio: View {
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @Environment(\.units) private var units

    let distance: String
    let climbing: String
    let time: String

    var body: some View {
        Group {
            if dynamicTypeSize.isAccessibilitySize {
                VStack(alignment: .leading, spacing: 12) {
                    FeedCardStat(label: "Distance", value: distance, unit: units.distanceUnit)
                    FeedCardStat(label: "Climbing", value: climbing, unit: units.elevationUnit)
                    FeedCardStat(label: "Time", value: time, unit: nil)
                }
            } else {
                HStack {
                    FeedCardStat(label: "Distance", value: distance, unit: units.distanceUnit)
                    Spacer()
                    FeedCardStat(label: "Climbing", value: climbing, unit: units.elevationUnit)
                    Spacer()
                    FeedCardStat(label: "Time", value: time, unit: nil)
                }
            }
        }
        .padding(.trailing, 6)
    }
}

/// A finalized, encrypted on-device Ride whose evidence did not meet the
/// existing upload threshold. It remains visible without pretending that a
/// backend Ride or upload operation exists.
private struct LocalSavedRideCard: View {
    @Environment(\.units) private var units
    let ride: LocalSavedRide
    let riderName: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 9) {
                AvatarView(name: riderName, size: 30)
                VStack(alignment: .leading, spacing: 1) {
                    Text(riderName ?? "")
                        .font(.footnote.weight(.medium))
                        .foregroundStyle(Theme.ink)
                    Text(Format.rideTimestamp(Format.isoParser.string(from: ride.summary.startedAt)))
                        .font(.caption2)
                        .foregroundStyle(Theme.gray)
                }
            }

            Text(Format.displayRideTitle(
                nil,
                startedAtISO: Format.isoParser.string(from: ride.summary.startedAt),
                placeLabel: nil
            ))
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(Theme.ink)
            Text("Saved on this device")
                .font(.caption)
                .foregroundStyle(Theme.gray)

            FeedCardStatTrio(
                distance: Format.distance(fromMeters: ride.summary.distanceM, units: units),
                climbing: Format.elevation(fromMeters: ride.summary.elevationM, units: units),
                time: Format.shortDuration(ride.summary.durationS)
            )
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 12)
        .background(Theme.feedCard)
        .overlay(
            RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous)
                .stroke(.white.opacity(0.06), lineWidth: 0.5)
        )
        .clipShape(RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous))
        .accessibilityElement(children: .combine)
    }
}

struct FeedDisplayItem: Identifiable {
    enum Source {
        case localSaved(LocalSavedRide)
        case existing(RideFeedItem)
    }

    let id: String
    let source: Source
}

enum FeedDisplayAssembler {
    static func merge(
        localSavedRides: [LocalSavedRide],
        items: [RideFeedItem]
    ) -> [FeedDisplayItem] {
        let local = localSavedRides.map {
            FeedDisplayItem(id: "local-saved:\($0.id)", source: .localSaved($0))
        }
        let existing = items.map {
            FeedDisplayItem(id: "existing:\($0.id)", source: .existing($0))
        }
        return (local + existing).enumerated().sorted { lhs, rhs in
            let left = startedAt(lhs.element)
            let right = startedAt(rhs.element)
            return left == right ? lhs.offset < rhs.offset : left > right
        }.map(\.element)
    }

    private static func startedAt(_ item: FeedDisplayItem) -> Date {
        switch item.source {
        case let .localSaved(ride):
            return ride.summary.startedAt
        case let .existing(item):
            switch item.source {
            case let .local(job):
                return job.localSummary.startedAt
            case let .server(ride):
                return Format.date(from: ride.startedAt) ?? .distantPast
            case let .activity(activity):
                return activity.occurredDate
            }
        }
    }
}

@MainActor
@Observable
final class FeedModel {
    typealias FeedPageLoader = @Sendable (FeedScope, String?, Int) async throws -> FeedPage
    typealias ServerRideLoader = @Sendable () async throws -> [Ride]
    typealias LocalJobLoader = @Sendable (RecordingOwner) async -> [RideUploadJob]?

    private enum RemoteSource {
        case feed(FeedPageLoader, any FeedCacheStoring)
        case legacy(ServerRideLoader)
    }

    var items: [RideFeedItem] = []
    private(set) var loaded = false
    private(set) var loadFailed = false
    private(set) var isShowingCachedData = false
    private(set) var hasMore = false
    private(set) var nextCursor: String?
    private(set) var isLoadingNextPage = false
    private(set) var paginationFailed = false
    let usesFixture: Bool
    /// ride id → (climb names, counted CAL) footer summary.
    var climbSummaries: [String: RideClimbSummary] = [:]
    private var lastSuccessfulServerRides: [Ride] = []
    private var feedActivities: [FeedActivity] = []
    private var currentLocalJobs: [RideUploadJob] = []
    private(set) var loadedOwner: RecordingOwner?
    private(set) var loadedScope: FeedScope?
    private var reloadGeneration = 0
    private let remoteSource: RemoteSource
    private let loadLocalJobs: LocalJobLoader

    struct RideClimbSummary {
        let names: [String]
    }

    init(
        loadFeedPage: @escaping FeedPageLoader = { scope, before, limit in
            try await APIClient.shared.feedPage(scope: scope, before: before, limit: limit)
        },
        loadLocalJobs: @escaping LocalJobLoader = { owner in
            await RideUploadRuntime.shared.jobs(owner: owner)
        },
        cache: any FeedCacheStoring = FileFeedCache.shared
    ) {
        remoteSource = .feed(loadFeedPage, cache)
        self.loadLocalJobs = loadLocalJobs
        usesFixture = false
    }

    /// Compatibility seam for the pre-social-feed lifecycle tests. Production
    /// never uses `/rides` for Home now.
    init(
        loadServerRides: @escaping ServerRideLoader,
        loadLocalJobs: @escaping LocalJobLoader = { owner in
            await RideUploadRuntime.shared.jobs(owner: owner)
        }
    ) {
        remoteSource = .legacy(loadServerRides)
        self.loadLocalJobs = loadLocalJobs
        usesFixture = false
    }

    #if DEBUG
    init(debugItems: [RideFeedItem], owner: RecordingOwner) {
        items = debugItems
        loaded = true
        loadedOwner = owner
        // Must match FeedView's one live scope — a mismatch silently
        // renders an empty feed (broke when the feed went global-only
        // 2026-08-17; caught by the fresh-eyes fixture walk 2026-08-21).
        loadedScope = .global
        usesFixture = true
        remoteSource = .legacy({ [] })
        loadLocalJobs = { _ in [] }
    }
    #endif

    func reload(owner: RecordingOwner?, scope: FeedScope = .following) async {
        reloadGeneration &+= 1
        let generation = reloadGeneration

        guard let owner, !owner.id.isEmpty, !owner.wallet.isEmpty else {
            reset(owner: nil, scope: nil)
            loadedOwner = nil
            loaded = true
            return
        }

        let identityChanged = loadedOwner != owner || loadedScope != scope
        if identityChanged {
            // Owner isolation happens synchronously, before any unavailable or
            // slow read can leave the prior rider's cards on screen.
            reset(owner: owner, scope: scope)
        }

        var cacheWasLoaded = false
        if identityChanged, case let .feed(_, cache) = remoteSource {
            if let cached = try? await cache.load(owner: owner, scope: scope) {
                guard isCurrent(generation, owner: owner, scope: scope) else { return }
                feedActivities = deduplicatedRides(cached.activities)
                hasMore = cached.hasMore && cached.nextCursor != nil
                nextCursor = hasMore ? cached.nextCursor : nil
                items = assembled(localJobs: currentLocalJobs, activities: feedActivities)
                loaded = true
                isShowingCachedData = true
                cacheWasLoaded = true
            }
        }

        // Local custody is the first feed truth: a server outage must not
        // erase a ride that this device has durably accepted for upload.
        let localJobs = await loadLocalJobs(owner)
        guard isCurrent(generation, owner: owner, scope: scope) else { return }
        if let localJobs {
            currentLocalJobs = localJobs
            renderItems()
        }
        loaded = !items.isEmpty

        do {
            switch remoteSource {
            case let .feed(loader, cache):
                let page = try await loader(scope, nil, 30)
                guard isCurrent(generation, owner: owner, scope: scope) else { return }
                feedActivities = deduplicatedRides(page.activities)
                hasMore = page.hasMore && page.nextCursor != nil
                nextCursor = hasMore ? page.nextCursor : nil
                lastSuccessfulServerRides = []
                let localAvailable = await refreshLocalJobs(owner: owner, initial: localJobs)
                guard isCurrent(generation, owner: owner, scope: scope) else { return }
                renderItems()
                loaded = localAvailable || !items.isEmpty
                loadFailed = !loaded
                isShowingCachedData = false
                paginationFailed = false
                if localAvailable || !feedActivities.isEmpty {
                    let snapshot = FeedCacheSnapshot(
                        owner: owner,
                        scope: scope,
                        activities: feedActivities,
                        hasMore: hasMore,
                        nextCursor: nextCursor
                    )
                    try? await cache.save(snapshot)
                }

            case let .legacy(loader):
                let fresh = try await loader()
                guard isCurrent(generation, owner: owner, scope: scope) else { return }
                // Failed rows are represented by the owner-bound local job.
                lastSuccessfulServerRides = fresh.filter { $0.status != "failed" }
                let localAvailable = await refreshLocalJobs(owner: owner, initial: localJobs)
                guard isCurrent(generation, owner: owner, scope: scope) else { return }
                renderItems()
                loaded = localAvailable || !items.isEmpty
                loadFailed = !loaded
            }
        } catch {
            guard isCurrent(generation, owner: owner, scope: scope) else { return }
            // Preserve both the newly loaded local truth and any server rides
            // from cache or this process. Unavailable is never projected as a
            // newly authoritative empty feed.
            loadFailed = true
            let cacheIsUsable = cacheWasLoaded && (localJobs != nil || !items.isEmpty)
            isShowingCachedData = cacheIsUsable || !feedActivities.isEmpty
            loaded = cacheIsUsable || loaded || !items.isEmpty
        }
    }

    func loadNextPage(owner: RecordingOwner?, scope: FeedScope) async {
        guard let owner,
              loadedOwner == owner,
              loadedScope == scope,
              hasMore,
              let cursor = nextCursor,
              !isLoadingNextPage,
              case let .feed(loader, cache) = remoteSource
        else { return }

        let generation = reloadGeneration
        isLoadingNextPage = true
        paginationFailed = false
        defer { isLoadingNextPage = false }

        do {
            let page = try await loader(scope, cursor, 20)
            guard isCurrent(generation, owner: owner, scope: scope) else { return }
            feedActivities = deduplicatedRides(feedActivities + page.activities)
            let advances = page.nextCursor != nil && page.nextCursor != cursor
            hasMore = page.hasMore && advances
            nextCursor = hasMore ? page.nextCursor : nil
            if let refreshedLocalJobs = await loadLocalJobs(owner) {
                guard isCurrent(generation, owner: owner, scope: scope) else { return }
                currentLocalJobs = refreshedLocalJobs
            }
            renderItems()
            let snapshot = FeedCacheSnapshot(
                owner: owner,
                scope: scope,
                activities: feedActivities,
                hasMore: hasMore,
                nextCursor: nextCursor
            )
            try? await cache.save(snapshot)
        } catch {
            guard isCurrent(generation, owner: owner, scope: scope) else { return }
            paginationFailed = true
        }
    }

    private func reset(owner: RecordingOwner?, scope: FeedScope?) {
        items = []
        loaded = false
        loadFailed = false
        isShowingCachedData = false
        hasMore = false
        nextCursor = nil
        isLoadingNextPage = false
        paginationFailed = false
        lastSuccessfulServerRides = []
        feedActivities = []
        currentLocalJobs = []
        climbSummaries = [:]
        loadedOwner = owner
        loadedScope = scope
    }

    private func isCurrent(
        _ generation: Int,
        owner: RecordingOwner,
        scope: FeedScope
    ) -> Bool {
        reloadGeneration == generation && loadedOwner == owner && loadedScope == scope
    }

    private func refreshLocalJobs(
        owner: RecordingOwner,
        initial: [RideUploadJob]?
    ) async -> Bool {
        if let refreshed = await loadLocalJobs(owner) {
            currentLocalJobs = refreshed
            return true
        } else if let initial {
            currentLocalJobs = initial
            return true
        }
        return false
    }

    private func renderItems() {
        switch remoteSource {
        case .feed:
            items = assembled(localJobs: currentLocalJobs, activities: feedActivities)
        case .legacy:
            items = assembled(
                localJobs: currentLocalJobs,
                serverRides: lastSuccessfulServerRides
            )
        }
    }

    private func deduplicatedRides(_ activities: [FeedActivity]) -> [FeedActivity] {
        var seen = Set<String>()
        return activities.filter { activity in
            guard activity.rideID != nil else { return false }
            return seen.insert(activity.deduplicationKey).inserted
        }
    }

    private func assembled(
        localJobs: [RideUploadJob],
        activities: [FeedActivity]
    ) -> [RideFeedItem] {
        let visibleActivities = activities.filter { activity in
            guard let rideID = activity.rideID else { return false }
            let matchingJobs = localJobs.filter { $0.serverRideID == rideID }
            guard !matchingJobs.isEmpty else { return true }
            return activity.status == "completed"
                && matchingJobs.allSatisfy { $0.phase == .final }
        }
        return RideFeedAssembler.merge(
            localJobs: localJobs,
            feedActivities: visibleActivities
        )
    }

    private func assembled(
        localJobs: [RideUploadJob],
        serverRides: [Ride]
    ) -> [RideFeedItem] {
        let visibleServerRides = serverRides.filter { ride in
            let matchingJobs = localJobs.filter { $0.serverRideID == ride.id }
            guard !matchingJobs.isEmpty else { return true }
            // List status alone cannot prove finality. Keep every matching
            // owner-bound job until its required owned status/detail/pattern
            // rereads have finalized it; only then may the final server card
            // replace the local projection.
            return ride.status == "completed"
                && matchingJobs.allSatisfy { $0.phase == .final }
        }
        return RideFeedAssembler.merge(
            localJobs: localJobs,
            serverRides: visibleServerRides
        )
    }

    func loadClimbSummary(for ride: Ride) async {
        guard climbSummaries[ride.id] == nil else { return }
        guard let response = try? await APIClient.shared.ridePatterns(id: ride.id) else { return }
        let names = (response.patterns?.climbPatterns ?? []).map(\.shownName)
        climbSummaries[ride.id] = RideClimbSummary(names: names)
    }
}

enum RideUploadFeedPresentation {
    /// Status is a fact, not a name: it renders as a small gray caption
    /// under the ride title, never as the title (bead c6l2l item 6).
    static func statusText(for phase: RideUploadPhase) -> String {
        switch phase {
        case .awaitingPrivacyReview:
            return "Saved on this device"
        case .failed:
            return "Processing failed"
        case .underReview:
            return "Under review"
        case .waitingForAuthentication:
            return "Signed out"
        case .queued, .initializing, .transferring, .completing, .processing, .retryable, .final:
            return "Processing"
        }
    }
}

/// The persisted ride's production feed projection. It reuses the final ride
/// card's header/stat grammar while withholding route, climb, CAL, and detail
/// navigation until authoritative server reads are final.
private struct LocalRideCard: View {
    @Environment(\.units) private var units
    let job: RideUploadJob
    let riderName: String?
    let onReview: (() -> Void)?
    let onRetry: (() -> Void)?

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            VStack(alignment: .leading, spacing: 10) {
                HStack(spacing: 9) {
                    AvatarView(name: riderName, size: 30)
                    VStack(alignment: .leading, spacing: 1) {
                        Text(riderName ?? "")
                            .font(.footnote.weight(.medium))
                            .foregroundStyle(Theme.ink)
                        Text(Format.rideTimestamp(Format.isoParser.string(from: job.localSummary.startedAt)))
                            .font(.caption2)
                            .foregroundStyle(Theme.gray)
                    }
                }

                // The title slot always holds the ride's name; status is a
                // quiet caption under it (bead c6l2l item 6).
                Text(Format.displayRideTitle(
                    nil,
                    startedAtISO: Format.isoParser.string(from: job.localSummary.startedAt),
                    placeLabel: nil
                ))
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(Theme.ink)
                Text(statusText)
                    .font(.caption)
                    .foregroundStyle(Theme.gray)

                statTrio

                if let onReview {
                    HStack {
                        Spacer()
                        Button("Review", action: onReview)
                            .font(.subheadline.weight(.medium))
                            .foregroundStyle(Theme.blue)
                            .buttonStyle(.plain)
                            .frame(minHeight: 44)
                    }
                } else if let onRetry {
                    HStack {
                        Spacer()
                        // Error-state recovery is gray; blue stays with the
                        // happy path (Review) and Record.
                        Button("Retry", action: onRetry)
                            .font(.subheadline.weight(.medium))
                            .foregroundStyle(Theme.gray)
                            .buttonStyle(.plain)
                            .frame(minHeight: 44)
                    }
                }
            }
            .padding(.horizontal, 14)
            .padding(.top, 12)
            .padding(.bottom, 12)
        }
        .background(Theme.feedCard)
        .overlay(
            RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous)
                .stroke(.white.opacity(0.06), lineWidth: 0.5)
        )
        .clipShape(RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous))
        .accessibilityElement(children: onReview == nil && onRetry == nil ? .combine : .contain)
    }

    private var statusText: String {
        RideUploadFeedPresentation.statusText(for: job.phase)
    }

    private var statTrio: some View {
        FeedCardStatTrio(
            distance: Format.distance(fromMeters: job.localSummary.distanceM, units: units),
            climbing: Format.elevation(fromMeters: job.localSummary.elevationM, units: units),
            time: Format.shortDuration(job.localSummary.durationS)
        )
    }
}

/// The production social-feed ride card. Public rider identity and a familiar
/// activity summary lead; photos/maps stay subordinate to the ride itself.
/// Feed whispers (Law 2): one CAL figure, and only on your own card — other
/// riders' cards never show money (Law 6), and no social organs (Law 7).
private struct FeedActivityCard: View {
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @Environment(\.units) private var units

    let activity: FeedActivity
    let isOwnRide: Bool

    private var metadata: FeedActivityMetadata? { activity.metadata }
    private var rider: FeedActor? { activity.rider }
    private var routeFragments: [[CLLocationCoordinate2D]] {
        RouteGeometry.fragments(from: metadata?.routePreview)
    }
    private var primaryMedia: RideMedia? {
        metadata?.primaryMedia ?? metadata?.media?.first
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            VStack(alignment: .leading, spacing: 10) {
                HStack(spacing: 9) {
                    AvatarView(name: rider?.shownName, url: rider?.avatarURL, size: 30)
                    VStack(alignment: .leading, spacing: 1) {
                        Text(rider?.shownName ?? "Rider")
                            .font(.footnote.weight(.medium))
                            .foregroundStyle(Theme.ink)
                        Text(headerSubtitle)
                            .font(.caption2)
                            .foregroundStyle(Theme.gray)
                    }
                }

                // The ratified fallback-title rule applies to every card:
                // the backend's literal "Ride" is unnamed, so the place or
                // time of day speaks instead.
                Text(Format.displayRideTitle(
                    activity.title,
                    startedAtISO: activity.occurredAt ?? activity.createdAt,
                    placeLabel: metadata?.routePreview?.placeLabel
                ))
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(Theme.ink)

                FeedCardStatTrio(
                    distance: Format.distance(fromMeters: metadata?.distanceM, units: units),
                    climbing: Format.elevation(fromMeters: metadata?.shownElevationM, units: units),
                    time: Format.shortDuration(metadata?.durationS)
                )
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 12)

            if let url = primaryMedia?.url.flatMap(URL.init(string:)) {
                RideMediaImage(url: url)
                    .frame(height: 190)
                    .clipped()
            } else if !routeFragments.isEmpty {
                RouteMapSnapshot(fragments: routeFragments)
                    .frame(height: 160)
            }

            if showsImpactStrip {
                impactStrip
            }
        }
        .background(Theme.feedCard)
        .overlay(
            RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous)
                .stroke(.white.opacity(0.06), lineWidth: 0.5)
        )
        .clipShape(RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous))
        .accessibilityElement(children: .combine)
        .accessibilityHint("Opens ride")
    }

    private var headerSubtitle: String {
        var parts = [Format.rideTimestamp(activity.occurredAt ?? activity.createdAt)]
        if let place = metadata?.routePreview?.placeLabel, !place.isEmpty {
            parts.append(place)
        }
        return parts.filter { !$0.isEmpty }.joined(separator: " · ")
    }

    private var showsImpactStrip: Bool {
        isOwnRide && (metadata?.calEarned ?? 0) > 0
    }

    private var impactStrip: some View {
        HStack {
            Spacer(minLength: 8)
            if let cal = metadata?.calEarned, cal > 0 {
                Text("\(Format.amount(cal)) CAL")
                    .font(.numeral(.footnote, weight: .semibold))
                    .monospacedDigit()
                    .foregroundStyle(Theme.ink)
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
        .frame(minHeight: 42)
    }
}

/// The legacy fixture/own-ride card retained for deterministic render seams.
struct RideCard: View {
    @Environment(\.units) private var units
    let ride: Ride
    let riderName: String?
    let climbSummary: FeedModel.RideClimbSummary?

    private var routeFragments: [[CLLocationCoordinate2D]] {
        RouteGeometry.fragments(from: ride.routePreview)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            VStack(alignment: .leading, spacing: 10) {
                HStack(spacing: 9) {
                    AvatarView(name: riderName, size: 30)
                    VStack(alignment: .leading, spacing: 1) {
                        Text(riderName ?? "")
                            .font(.footnote.weight(.medium))
                            .foregroundStyle(Theme.ink)
                        Text(headerSubtitle)
                            .font(.caption2)
                            .foregroundStyle(Theme.gray)
                    }
                }
                Text(Format.displayRideTitle(
                    ride.title,
                    startedAtISO: ride.startedAt,
                    placeLabel: ride.routePreview?.placeLabel
                ))
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(Theme.ink)
                // Status never occupies the title slot — a quiet caption
                // under the title (bead c6l2l item 6).
                if ride.status == "under_review" {
                    Text("Under review")
                        .font(.caption)
                        .foregroundStyle(Theme.gray)
                }
                statTrio
            }
            .padding(.horizontal, 14)
            .padding(.top, 12)
            .padding(.bottom, 12)

            if !routeFragments.isEmpty {
                RouteMapSnapshot(fragments: routeFragments)
                    .frame(height: 148)
            }

            footer
        }
        .background(Theme.feedCard)
        .overlay(
            RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous)
                .stroke(.white.opacity(0.06), lineWidth: 0.5)
        )
        .clipShape(RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous))
        .accessibilityElement(children: .combine)
    }

    private var headerSubtitle: String {
        var parts = [Format.rideTimestamp(ride.startedAt)]
        if let place = ride.routePreview?.placeLabel, !place.isEmpty {
            parts.append(place)
        }
        return parts.joined(separator: " · ")
    }

    private var statTrio: some View {
        FeedCardStatTrio(
            distance: Format.distance(fromMeters: ride.distanceM, units: units),
            climbing: Format.elevation(fromMeters: ride.shownElevationM, units: units),
            time: Format.shortDuration(ride.durationS)
        )
    }

    @ViewBuilder
    private var footer: some View {
        let names = climbSummary?.names ?? []
        let cal = ride.calEarned ?? ride.earnings?.calEarned
        if !names.isEmpty || (cal ?? 0) > 0 {
            HStack(spacing: 8) {
                Image(systemName: "mountain.2")
                    .font(.caption)
                    .foregroundStyle(Theme.gray)
                    .accessibilityHidden(true)
                Text(truncatedNames(names))
                    .font(.caption)
                    .foregroundStyle(Theme.gray)
                    .lineLimit(1)
                Spacer(minLength: 8)
                if let cal, cal > 0 {
                    Text("\(Format.amount(cal)) CAL")
                        .font(.numeral(.footnote, weight: .semibold))
                        .monospacedDigit()
                        .foregroundStyle(Theme.ink)
                }
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 11)
        }
    }

    /// Apple-style truncation ("+2"), never wraps, never marquees.
    private func truncatedNames(_ names: [String]) -> String {
        if names.count <= 2 { return names.joined(separator: ", ") }
        return names.prefix(2).joined(separator: ", ") + " +\(names.count - 2)"
    }
}
