#if DEBUG
import Foundation
import SwiftUI
import UIKit

enum RidePublicationReviewRenderFixtureMode: String, CaseIterable, Sendable {
    case defaults
    case onlyYou = "only-you"
    case drafted
    case unavailable

    static let launchArgument = "-BRRidePublicationReviewRenderFixture"

    init?(arguments: [String]) {
        guard arguments.filter({ $0 == Self.launchArgument }).count == 1,
              let index = arguments.firstIndex(of: Self.launchArgument),
              arguments.indices.contains(index + 1)
        else { return nil }
        self.init(rawValue: arguments[index + 1])
    }
}

@MainActor
struct RidePublicationReviewRenderFixtureRoot: View {
    let mode: RidePublicationReviewRenderFixtureMode

    var body: some View {
        RidePublicationReviewView(
            job: fixtureJob,
            loadSettings: {
                if mode == .unavailable {
                    throw FixturePrivacyError.unavailable
                }
                return PrivacySettings(
                    contractVersion: "privacy.v2",
                    profileVisibility: "public",
                    defaultRideVisibility: mode == .onlyYou ? .onlyYou : .everyone,
                    defaultMapVisibility: mode == .onlyYou ? .hideEntire : .hideStartEnd,
                    defaultMapHideStartM: 200,
                    defaultMapHideEndM: 200,
                    defaultsApplyTo: "future_rides",
                    privacyZoneCount: 1,
                    privacyZonesLoaded: true,
                    rideOverrideMode: "optional",
                    protocolPublicFields: []
                )
            },
            initialTitle: mode == .drafted ? "Barren Hill before lunch" : "",
            initialNotes: mode == .drafted
                ? "Quiet roads, a steady north wind, and one clean run up the hill."
                : "",
            initialPhotos: mode == .drafted ? fixturePhotos : [],
            onSave: { _, _, _ in },
            onLater: {}
        )
    }

    private var fixturePhotos: [RidePhotoSelection] {
        [
            fixturePhoto(id: "11111111-1111-4111-8111-111111111111", warm: true),
            fixturePhoto(id: "22222222-2222-4222-8222-222222222222", warm: false),
        ]
    }

    private func fixturePhoto(id: String, warm: Bool) -> RidePhotoSelection {
        let image = UIGraphicsImageRenderer(size: CGSize(width: 320, height: 180)).image { context in
            let colors = warm
                ? [UIColor.systemOrange.cgColor, UIColor.systemIndigo.cgColor]
                : [UIColor.systemTeal.cgColor, UIColor.systemBlue.cgColor]
            let gradient = CGGradient(
                colorsSpace: CGColorSpaceCreateDeviceRGB(),
                colors: colors as CFArray,
                locations: [0, 1]
            )!
            context.cgContext.drawLinearGradient(
                gradient,
                start: .zero,
                end: CGPoint(x: 320, y: 180),
                options: []
            )
            context.cgContext.setStrokeColor(UIColor.white.withAlphaComponent(0.85).cgColor)
            context.cgContext.setLineWidth(5)
            context.cgContext.move(to: CGPoint(x: 0, y: 145))
            context.cgContext.addCurve(
                to: CGPoint(x: 320, y: 120),
                control1: CGPoint(x: 80, y: 70),
                control2: CGPoint(x: 210, y: 170)
            )
            context.cgContext.strokePath()
        }
        return try! RidePhotoSelection(
            id: id,
            fileName: warm ? "barren-hill.jpg" : "river-road.jpg",
            mimeType: "image/jpeg",
            data: image.jpegData(compressionQuality: 0.85)!
        )
    }

    private var fixtureJob: RideUploadJob {
        let startedAt = Date(timeIntervalSince1970: 1_786_703_100)
        return RideUploadJob(
            id: "88888888-8888-4888-8888-888888888888",
            ownerID: "debug-rider",
            ownerWallet: "debug-wallet",
            fileName: "Friday Ride.gpx",
            fileType: "gpx",
            fileHash: String(repeating: "a", count: 64),
            fileSize: 1_024,
            sourceFileName: "source.gpx",
            localSummary: LocalRideSummary(
                startedAt: startedAt,
                distanceM: 28_485.2,
                elevationM: 472.4,
                durationS: 4_382
            ),
            createdAt: startedAt.addingTimeInterval(4_382),
            updatedAt: startedAt.addingTimeInterval(4_382),
            phase: .awaitingPrivacyReview,
            attemptedServerHandoff: false,
            signedURL: nil,
            signedURLExpiresAt: nil,
            serverRideID: nil,
            authoritativeStatus: nil,
            attemptCount: 0,
            nextRetryAt: nil,
            lastError: nil,
            canRetry: false,
            revealState: .none,
            reveal: nil
        )
    }
}

private enum FixturePrivacyError: Error {
    case unavailable
}
#endif
