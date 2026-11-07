#if DEBUG
import CoreLocation
import Foundation
import SwiftUI

/// Route-rendering unification evidence seam (bead boulderroller-v2-zudgp).
/// Feeds a real route_preview.v1 JSON document (e.g. one built by the backend
/// contract over a real Philadelphia fixture ride) through the production
/// RideCard / MapViewerView render paths. The fixture supplies data only —
/// every drawing code path is the production one.
enum RouteRenderFixtureMode: String, CaseIterable {
    case feed
    case viewer
    /// Every feed card variant on one screen (bead c6l2l items 3/4/6/7):
    /// server card with route, under-review server card without route,
    /// processing local card, saved-on-device card, and the inline
    /// custody-unavailable state.
    case feedCards

    static let launchArgument = "-BRRouteRenderFixture"
    static let previewPathEnvironment = "BR_ROUTE_RENDER_FIXTURE_PREVIEW_PATH"

    init?(arguments: [String]) {
        guard arguments.filter({ $0 == Self.launchArgument }).count == 1,
              let index = arguments.firstIndex(of: Self.launchArgument),
              arguments.indices.contains(index + 1)
        else { return nil }
        self.init(rawValue: arguments[index + 1])
    }

    static func loadPreview() -> RoutePreview? {
        guard let path = ProcessInfo.processInfo.environment[previewPathEnvironment],
              let data = FileManager.default.contents(atPath: path)
        else { return nil }
        return try? JSONDecoder().decode(RoutePreview.self, from: data)
    }
}

@MainActor
struct RouteRenderFixtureRoot: View {
    let mode: RouteRenderFixtureMode
    @State private var session: AppSession

    private let preview = RouteRenderFixtureMode.loadPreview() ?? RoutePreview(
        source: "fixture",
        points: [
            RoutePreviewPoint(x: 0.08, y: 0.82),
            RoutePreviewPoint(x: 0.22, y: 0.68),
            RoutePreviewPoint(x: 0.43, y: 0.73),
            RoutePreviewPoint(x: 0.61, y: 0.48),
            RoutePreviewPoint(x: 0.82, y: 0.31),
            RoutePreviewPoint(x: 0.94, y: 0.12),
        ],
        segments: nil,
        bounds: RoutePreviewBounds(
            minLat: 39.94,
            minLon: -75.28,
            maxLat: 40.02,
            maxLon: -75.18
        ),
        placeLabel: "Philadelphia, PA",
        fallbackReason: nil
    )

    init(mode: RouteRenderFixtureMode) {
        self.mode = mode
        let session = AppSession()
        session.phase = .signedIn(RideUploadRenderFixtureData.rider)
        session.hasUncollectedSettlements = nil
        _session = State(initialValue: session)
    }

    private var ride: Ride {
        Ride(
            id: "77777777-7777-4777-8777-777777777773",
            title: nil,
            status: "completed",
            startedAt: "2026-08-09T11:14:00Z",
            distanceM: 4_988,
            elevationM: nil,
            elevationCorrectedM: 75,
            elevationCorrection: nil,
            durationS: 1_030,
            avgPowerW: nil,
            normalizedPowerW: nil,
            avgHrBpm: nil,
            tss: nil,
            calEarned: nil,
            tributableCal: nil,
            rewardableCal: nil,
            routePreview: preview,
            earnings: nil,
            calItemization: nil,
            isOwner: true
        )
    }

    private var underReviewRide: Ride {
        Ride(
            id: "77777777-7777-4777-8777-777777777774",
            title: nil,
            status: "under_review",
            startedAt: "2026-08-08T21:49:00Z",
            distanceM: 1_770,
            elevationM: nil,
            elevationCorrectedM: 111,
            elevationCorrection: nil,
            durationS: 420,
            avgPowerW: nil,
            normalizedPowerW: nil,
            avgHrBpm: nil,
            tss: nil,
            calEarned: nil,
            tributableCal: nil,
            rewardableCal: nil,
            routePreview: nil,
            earnings: nil,
            calItemization: nil,
            isOwner: true
        )
    }

    private var photoFeedActivity: FeedActivity {
        FeedActivity(
            id: "77777777-7777-4777-8777-777777777771",
            type: "ride",
            eventType: "ride_completed",
            title: "Lunch Ride",
            createdAt: "2026-08-14T16:05:00Z",
            occurredAt: "2026-08-14T16:05:00Z",
            status: "completed",
            actor: FeedActor(
                id: "fixture-rider",
                username: "gabe",
                displayName: "Gabe",
                avatarUrl: nil
            ),
            user: nil,
            target: FeedTarget(type: "ride", id: "77777777-7777-4777-8777-777777777771"),
            metadata: FeedActivityMetadata(
                distanceM: 31_400,
                elevationM: 620,
                elevationCorrectedM: 598,
                durationS: 4_680,
                dungEarned: 18,
                calEarned: 86,
                status: "completed",
                kudosCount: 7,
                commentCount: 2,
                viewerHasKudos: true,
                media: [fixtureMedia],
                primaryMedia: fixtureMedia,
                routePreview: preview
            ),
            privacy: nil
        )
    }

    private var mapFeedActivity: FeedActivity {
        FeedActivity(
            id: "77777777-7777-4777-8777-777777777772",
            type: "ride",
            eventType: "ride_completed",
            title: "Morning Ride",
            createdAt: "2026-08-13T11:14:00Z",
            occurredAt: "2026-08-13T11:14:00Z",
            status: "completed",
            actor: FeedActor(
                id: "fixture-friend",
                username: "maya",
                displayName: "Maya",
                avatarUrl: nil
            ),
            user: nil,
            target: FeedTarget(type: "ride", id: "77777777-7777-4777-8777-777777777772"),
            metadata: FeedActivityMetadata(
                distanceM: 4_988,
                elevationM: 80,
                elevationCorrectedM: 75,
                durationS: 1_030,
                dungEarned: nil,
                calEarned: 12,
                status: "completed",
                kudosCount: 1,
                commentCount: 0,
                viewerHasKudos: false,
                media: nil,
                primaryMedia: nil,
                routePreview: preview
            ),
            privacy: nil
        )
    }

    private var fixtureMedia: RideMedia {
        RideMedia(
            id: "77777777-7777-4777-8777-777777777770",
            rideId: "77777777-7777-4777-8777-777777777771",
            url: "br-fixture://warm/cover",
            fileName: "ride.jpg",
            mimeType: "image/jpeg",
            sizeBytes: 120_000,
            width: 1_200,
            height: 900,
            sortOrder: 0,
            role: "cover",
            moderationState: "visible",
            createdAt: "2026-08-14T16:06:00Z"
        )
    }

    private var savedRide: LocalSavedRide {
        LocalSavedRide(
            id: "77777777-7777-4777-8777-777777777775",
            ownerID: RideUploadRenderFixtureData.rider.id,
            ownerWallet: RideUploadRenderFixtureData.rider.wallet,
            summary: LocalRideSummary(
                startedAt: Date(timeIntervalSince1970: 1_786_305_000),
                distanceM: 3_540,
                elevationM: nil,
                durationS: 900
            ),
            fileHash: String(repeating: "b", count: 64),
            preliminaryRideHash: String(repeating: "c", count: 64),
            parserVersion: 1
        )
    }

    var body: some View {
        switch mode {
        case .feed:
            FeedView(
                debugItems: [
                    RideFeedItem(id: photoFeedActivity.id, source: .activity(photoFeedActivity)),
                    RideFeedItem(id: mapFeedActivity.id, source: .activity(mapFeedActivity)),
                ],
                owner: RecordingOwner(user: RideUploadRenderFixtureData.rider)
            )
            .environment(session)
        case .feedCards:
            let processingJob = RideUploadRenderFixtureData.job(phase: .processing)
            FeedView(
                debugItems: [
                    RideFeedItem(id: ride.id, source: .server(ride)),
                    RideFeedItem(id: underReviewRide.id, source: .server(underReviewRide)),
                    RideFeedItem(id: processingJob.id, source: .local(processingJob)),
                ],
                owner: RecordingOwner(user: RideUploadRenderFixtureData.rider)
            )
            .environment(session)
            .onAppear {
                session.localSavedRides = [savedRide]
                session.interruptedRideErrorMessage = "Ride evidence is unavailable"
            }
        case .viewer:
            MapViewerView(
                fragments: RouteGeometry.fragments(from: preview),
                title: Format.displayRideTitle(
                    nil,
                    startedAtISO: ride.startedAt,
                    placeLabel: preview.placeLabel
                ),
                subtitle: nil,
                destinationClimbId: nil
            )
            .environment(session)
        }
    }
}
#endif
