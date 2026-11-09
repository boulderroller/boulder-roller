import XCTest
@testable import BoulderRoller

/// Batch C item 4 (bead boulderroller-v2-f4acp.1.9): profile editing writes
/// the exact `PUT /users/me` contract, and the avatar lane can only succeed
/// through `complete` returning the refreshed profile — a storage PUT alone
/// is never rendered as success.
final class ProfileEditContractTests: XCTestCase {
    private let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }()

    private func decodeUser(_ json: String) -> User {
        try! decoder.decode(User.self, from: Data(json.utf8))
    }

    private var rider: User {
        decodeUser(
            """
            {"id": "u1", "wallet": "W1", "display_name": "Tim",
             "location": "Manayunk", "avatar_url": "https://example/a.jpg"}
            """
        )
    }

    // MARK: PUT /users/me body (double-optional: absent / value / null)

    func testProfileUpdateBodyCarriesOnlyChangedFields() {
        let nameOnly = APIClient.profileUpdateBody(displayName: .some("Tim W"))
        XCTAssertEqual(nameOnly["display_name"] as? String, "Tim W")
        XCTAssertNil(nameOnly["location"])

        let locationOnly = APIClient.profileUpdateBody(location: .some("Fishtown"))
        XCTAssertNil(locationOnly["display_name"])
        XCTAssertEqual(locationOnly["location"] as? String, "Fishtown")

        let bioOnly = APIClient.profileUpdateBody(bio: .some("Hills before coffee."))
        XCTAssertNil(bioOnly["display_name"])
        XCTAssertNil(bioOnly["location"])
        XCTAssertEqual(bioOnly["bio"] as? String, "Hills before coffee.")

        XCTAssertTrue(APIClient.profileUpdateBody().isEmpty)
    }

    /// A clear ships the EMPTY STRING, not JSON null: the backend's
    /// `update_user_profile` drops nulls for identity fields (only
    /// physiology is null-clearable), so a null clear would be a silent
    /// no-op misreported as success. Empty string persists server-side.
    func testProfileClearSendsEmptyStringBecauseServerDropsNulls() {
        let cleared = APIClient.profileUpdateBody(
            displayName: .some(nil), location: .some(nil), bio: .some(nil)
        )
        XCTAssertEqual(cleared["display_name"] as? String, "")
        XCTAssertEqual(cleared["location"] as? String, "")
        XCTAssertEqual(cleared["bio"] as? String, "")
    }

    /// Rendering treats a persisted empty-string clear as absence — no
    /// surface may show an empty name.
    func testShownNameTreatsEmptyStringAsAbsence() {
        let cleared = decodeUser(
            #"{"id": "u1", "wallet": "WXYZ9", "display_name": "", "username": ""}"#
        )
        XCTAssertEqual(cleared.shownName, "Rider WXYZ")
        let usernameOnly = decodeUser(
            #"{"id": "u1", "wallet": "W1", "display_name": "", "username": "timw"}"#
        )
        XCTAssertEqual(usernameOnly.shownName, "timw")
    }

    func testProfileLimitsMirrorServerValidation() {
        XCTAssertEqual(ProfileEditContract.maxDisplayNameLength, 50)
        XCTAssertEqual(ProfileEditContract.maxLocationLength, 100)
    }

    // MARK: Avatar media contract (mirror of avatar_media_contracts.py)

    func testMimeNormalizationMatchesServer() {
        XCTAssertEqual(AvatarMediaContract.normalizedMimeType("image/jpg"), "image/jpeg")
        XCTAssertEqual(
            AvatarMediaContract.normalizedMimeType("IMAGE/JPEG; charset=binary"),
            "image/jpeg"
        )
        XCTAssertEqual(AvatarMediaContract.normalizedMimeType("image/HEIC"), "image/heic")
    }

    func testPreflightMirrorsServerRefusals() {
        XCTAssertNil(
            AvatarUploadModel.preflightFailure(mimeType: "image/png", byteCount: 1_000)
        )
        XCTAssertEqual(
            AvatarUploadModel.preflightFailure(mimeType: "image/gif", byteCount: 1_000),
            "Avatar must be a JPEG, PNG, WebP, HEIC, or HEIF image."
        )
        XCTAssertEqual(
            AvatarUploadModel.preflightFailure(
                mimeType: "image/jpeg",
                byteCount: AvatarMediaContract.maxFileSizeBytes + 1
            ),
            "Avatar must be 15 MB or smaller."
        )
        XCTAssertNotNil(
            AvatarUploadModel.preflightFailure(mimeType: "image/jpeg", byteCount: 0)
        )
    }

    func testFileExtensionFollowsMime() {
        XCTAssertEqual(AvatarUploadModel.fileExtension(for: "image/png"), "png")
        XCTAssertEqual(AvatarUploadModel.fileExtension(for: "image/heic"), "heic")
        XCTAssertEqual(AvatarUploadModel.fileExtension(for: "image/jpeg"), "jpg")
    }

    // MARK: Upload lifecycle — success only through complete

    @MainActor
    func testUploadRunsInitPutCompleteInOrderAndAdoptsProfile() async {
        let model = AvatarUploadModel()
        var order: [String] = []
        model.initUpload = { mime, _, size in
            order.append("init")
            XCTAssertEqual(mime, "image/jpeg")
            XCTAssertEqual(size, 3)
            return AvatarUploadInit(uploadId: "up1", signedUrl: "https://s/u", expiresIn: 3600)
        }
        model.putToStorage = { url, data, name in
            order.append("put")
            XCTAssertEqual(url, "https://s/u")
            XCTAssertEqual(data.count, 3)
            XCTAssertEqual(name, "avatar.jpg")
        }
        let updated = rider
        model.completeUpload = { uploadId in
            order.append("complete")
            XCTAssertEqual(uploadId, "up1")
            return updated
        }

        let result = await model.upload(
            data: Data([1, 2, 3]), mimeType: "image/jpg"
        )
        XCTAssertEqual(order, ["init", "put", "complete"])
        XCTAssertEqual(result?.id, "u1")
        XCTAssertEqual(model.phase, .idle)
    }

    /// The core honesty proof: storage PUT succeeded, complete failed —
    /// there is NO success, the failure stands, no profile is returned.
    @MainActor
    func testCompleteFailureAfterStoragePutIsNeverSuccess() async {
        let model = AvatarUploadModel()
        model.initUpload = { _, _, _ in
            AvatarUploadInit(uploadId: "up1", signedUrl: "https://s/u", expiresIn: 3600)
        }
        model.putToStorage = { _, _, _ in }
        model.completeUpload = { _ in
            throw APIError.http(
                status: 400, code: nil,
                message: "Avatar not found in storage. Upload may have failed or expired."
            )
        }

        let result = await model.upload(data: Data([1]), mimeType: "image/png")
        XCTAssertNil(result)
        guard case let .failed(message) = model.phase else {
            return XCTFail("expected standing failure, got \(model.phase)")
        }
        XCTAssertTrue(message.contains("Upload may have failed"))
    }

    @MainActor
    func testInitConflictSurfacesServerMessage() async {
        let model = AvatarUploadModel()
        model.initUpload = { _, _, _ in
            throw APIError.http(
                status: 409, code: nil,
                message: "An avatar upload is already pending. Complete or delete it before starting another."
            )
        }
        model.putToStorage = { _, _, _ in XCTFail("must not reach storage") }
        model.completeUpload = { _ in
            XCTFail("must not reach complete")
            throw APIError.notAuthenticated
        }

        let result = await model.upload(data: Data([1]), mimeType: "image/jpeg")
        XCTAssertNil(result)
        guard case let .failed(message) = model.phase else {
            return XCTFail("expected failed, got \(model.phase)")
        }
        XCTAssertTrue(message.contains("already pending"))
    }

    /// Refused media never leaves the device: no init, no storage traffic.
    @MainActor
    func testPreflightRefusalMakesNoNetworkCalls() async {
        let model = AvatarUploadModel()
        model.initUpload = { _, _, _ in
            XCTFail("refused media must not init")
            throw APIError.notAuthenticated
        }
        let result = await model.upload(data: Data([1]), mimeType: "image/gif")
        XCTAssertNil(result)
        if case .failed = model.phase {} else {
            XCTFail("expected failed, got \(model.phase)")
        }
    }

    @MainActor
    func testRemoveAdoptsServerProfileOrStandsFailed() async {
        let model = AvatarUploadModel()
        let cleared = decodeUser(#"{"id": "u1", "wallet": "W1"}"#)
        model.deleteAvatar = { cleared }
        let removed = await model.remove()
        XCTAssertEqual(removed?.id, "u1")
        XCTAssertNil(removed?.avatarUrl)
        XCTAssertEqual(model.phase, .idle)

        model.deleteAvatar = {
            throw APIError.http(status: 503, code: nil, message: "Please retry.")
        }
        let failed = await model.remove()
        XCTAssertNil(failed)
        guard case .failed = model.phase else {
            return XCTFail("expected failed, got \(model.phase)")
        }
    }

    // MARK: Session adoption is identity-pinned

    @MainActor
    func testSessionAdoptsUpdatesOnlyForTheSameAccount() {
        let session = AppSession(
            accountDeletionCapabilityStore: SessionDeletionCapabilityStore(capability: nil)
        )
        session.phase = .signedIn(rider)

        let renamed = decodeUser(
            #"{"id": "u1", "wallet": "W1", "display_name": "Timothy"}"#
        )
        session.adoptUpdatedUser(renamed)
        XCTAssertEqual(session.currentUser?.displayName, "Timothy")

        let stranger = decodeUser(#"{"id": "u2", "wallet": "W2"}"#)
        session.adoptUpdatedUser(stranger)
        XCTAssertEqual(session.currentUser?.id, "u1", "another account's profile is refused")
    }
}
