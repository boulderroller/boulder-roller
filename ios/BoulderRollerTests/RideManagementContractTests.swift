import Foundation
import Testing
@testable import BoulderRoller

/// L2.05 native ride management truth guards: deletion is only ever
/// claimed on explicit server confirmation, and an inaccessible original
/// never becomes an empty or insecure download.
struct RideManagementContractTests {
    @Test func deletionRequiresExplicitConfirmationForExactlyThisRide() {
        #expect(APIClient.confirmsDeletion(
            RideDeleteResponse(status: "deleted", rideId: "r1"), id: "r1"
        ))
        // Queued/other statuses are not deletion.
        #expect(!APIClient.confirmsDeletion(
            RideDeleteResponse(status: "queued", rideId: "r1"), id: "r1"
        ))
        // A confirmation for a different ride proves nothing about this one.
        #expect(!APIClient.confirmsDeletion(
            RideDeleteResponse(status: "deleted", rideId: "r2"), id: "r1"
        ))
    }

    @Test func originalDownloadRefusesInsecureOrUnparseableURLs() {
        func original(_ url: String) -> RideOriginalFile {
            RideOriginalFile(
                signedUrl: url, fileName: "Ride.fit", fileType: "fit",
                mimeType: "application/octet-stream", expiresIn: 600
            )
        }
        #expect(APIClient.validatedOriginalURL(
            original("https://storage.example/signed")
        ) != nil)
        #expect(APIClient.validatedOriginalURL(
            original("http://storage.example/signed")
        ) == nil)
        #expect(APIClient.validatedOriginalURL(original("")) == nil)
        #expect(APIClient.validatedOriginalURL(
            original("not a url at all ~~ ")
        ) == nil)
    }
}
