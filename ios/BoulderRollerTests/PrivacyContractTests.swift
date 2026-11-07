import XCTest
@testable import BoulderRoller

/// Batch C item 1 + 2 (beads boulderroller-v2-f4acp.1.4, joer2 contract):
/// the client mirrors the backend privacy engine exactly — zone constraints,
/// the three-value audience vocabulary, the ratified exposure default — and
/// an unavailable contract renders unavailable, never a guessed default.
final class PrivacyContractTests: XCTestCase {
    /// The production client's decoding configuration.
    private let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }()

    // MARK: Vocabulary — wire-exact values, ratified labels

    func testRideVisibilityMirrorsBackendWireValues() {
        XCTAssertEqual(RideVisibility.everyone.rawValue, "public")
        XCTAssertEqual(RideVisibility.followers.rawValue, "followers")
        XCTAssertEqual(RideVisibility.onlyYou.rawValue, "private")
        XCTAssertEqual(RideVisibility.allCases.count, 3)
    }

    func testRideVisibilityLabelsAreTheRatifiedStravaShapedSet() {
        XCTAssertEqual(RideVisibility.everyone.label, "Everyone")
        XCTAssertEqual(RideVisibility.followers.label, "Followers")
        XCTAssertEqual(RideVisibility.onlyYou.label, "Only you")
    }

    func testMapVisibilityMirrorsBackendWireValues() {
        XCTAssertEqual(RideMapVisibility.showAll.rawValue, "show_all")
        XCTAssertEqual(RideMapVisibility.hideStartEnd.rawValue, "hide_start_end")
        XCTAssertEqual(RideMapVisibility.hideEntire.rawValue, "hide_entire")
    }

    /// Backend `ALLOWED_PRIVACY_ZONE_RADII_M = {200, 400, 800, 1600}` —
    /// mirrored exactly, no invented presets.
    func testZoneRadiusPresetsMirrorBackendAllowedSet() {
        XCTAssertEqual(
            PrivacyZoneRadius.allCases.map(\.rawValue),
            [200, 400, 800, 1600]
        )
        XCTAssertEqual(PrivacyZoneRadius.maxLabelLength, 50)
        // Labels follow the rider's units: exact meters for Kilometers, the
        // imperial ladder the radii were chosen from for Miles (2026-08-21).
        XCTAssertEqual(PrivacyZoneRadius.allCases.map { $0.label(units: .metric) }, ["200 m", "400 m", "800 m", "1,600 m"])
        XCTAssertEqual(PrivacyZoneRadius.allCases.map { $0.label(units: .imperial) }, ["⅛ mi", "¼ mi", "½ mi", "1 mi"])
    }

    /// The single documented exposure-default constant pins the joer2
    /// ratification (2026-08-02): Everyone, first/last 200 m hidden. The
    /// client never guesses from this mirror: it loads the rider's current
    /// server defaults and writes the explicit reviewed snapshot.
    func testExposureDefaultsPinTheRatifiedContract() {
        XCTAssertEqual(ExposureDefaults.ratifiedDefaultVisibility, .everyone)
        XCTAssertEqual(ExposureDefaults.ratifiedDefaultMapVisibility, .hideStartEnd)
        XCTAssertEqual(ExposureDefaults.ratifiedDefaultMapHideStartM, 200)
        XCTAssertEqual(ExposureDefaults.ratifiedDefaultMapHideEndM, 200)
    }

    // MARK: Wire decoding — real response shapes

    func testDecodesPrivacySettingsWireShape() throws {
        // GET /privacy/settings serializes by alias (camelCase).
        let json = """
        {
          "contractVersion": "privacy.v2",
          "profileVisibility": "public",
          "defaultRideVisibility": "public",
          "defaultMapVisibility": "hide_start_end",
          "defaultMapHideStartM": 200,
          "defaultMapHideEndM": 200,
          "defaultsApplyTo": "future_rides",
          "providerPrivacyInherited": false,
          "privacyZoneCount": 1,
          "privacyZonesLoaded": true,
          "rideOverrideMode": "optional",
          "protocolPublicFields": ["ride_hash_hex"]
        }
        """
        let settings = try decoder.decode(PrivacySettings.self, from: Data(json.utf8))
        XCTAssertEqual(settings.defaultRideVisibility, .everyone)
        XCTAssertEqual(settings.defaultMapVisibility, .hideStartEnd)
        XCTAssertEqual(settings.defaultMapHideStartM, 200)
        XCTAssertEqual(settings.defaultMapHideEndM, 200)
        XCTAssertEqual(settings.defaultsApplyTo, "future_rides")
        XCTAssertEqual(settings.privacyZoneCount, 1)
        XCTAssertEqual(settings.privacyZonesLoaded, true)
    }

    func testDecodesZoneListWireShape() throws {
        // GET /privacy/zones serializes snake_case.
        let json = """
        {
          "zones": [
            {
              "id": "3f0e8d1a-1111-2222-3333-444455556666",
              "latitude": 39.9526,
              "longitude": -75.1652,
              "radius_m": 400,
              "label": "Home",
              "created_at": "2026-08-12T00:00:00+00:00",
              "updated_at": "2026-08-12T00:00:00+00:00"
            }
          ],
          "max_zones": 5
        }
        """
        let list = try decoder.decode(PrivacyZonesList.self, from: Data(json.utf8))
        XCTAssertEqual(list.zones.count, 1)
        XCTAssertEqual(list.zones[0].radiusM, 400)
        XCTAssertEqual(list.zones[0].label, "Home")
        XCTAssertEqual(list.maxZones, 5)
    }

    func testDecodesRideDetailPrivacyState() throws {
        // The `privacy` object attached to ride records (PrivacyState).
        let json = """
        {
          "visibility": "followers",
          "canView": true,
          "isOwner": true,
          "isFollower": false,
          "redactGps": false,
          "mapVisibility": "hide_start_end",
          "mapHideStartM": 200,
          "mapHideEndM": 200,
          "protocolPublic": false,
          "protocolPublicFields": [],
          "reason": "owner"
        }
        """
        let state = try decoder.decode(RidePrivacyState.self, from: Data(json.utf8))
        XCTAssertEqual(state.visibility, .followers)
        XCTAssertEqual(state.isOwner, true)
        XCTAssertEqual(state.mapVisibility, .hideStartEnd)
        XCTAssertEqual(state.mapHideStartM, 200)
    }

    /// A ride without the privacy object still decodes — older cached rows
    /// simply render no audience row rather than failing the whole surface.
    func testRideDecodesWithoutPrivacyObject() throws {
        let json = """
        {"id": "r1", "started_at": "2026-08-12T00:00:00+00:00"}
        """
        let ride = try decoder.decode(Ride.self, from: Data(json.utf8))
        XCTAssertNil(ride.privacy)
    }

    // MARK: Request bodies — wire-exact writes

    func testZoneCreateBodyMatchesBackendContract() {
        let body = APIClient.privacyZoneBody(
            latitude: 39.9526, longitude: -75.1652, radiusM: 400, label: "Home"
        )
        XCTAssertEqual(body["latitude"] as? Double, 39.9526)
        XCTAssertEqual(body["longitude"] as? Double, -75.1652)
        XCTAssertEqual(body["radius_m"] as? Int, 400)
        XCTAssertEqual(body["label"] as? String, "Home")
    }

    func testZoneCreateBodyOmitsEmptyLabel() {
        let body = APIClient.privacyZoneBody(
            latitude: 1, longitude: 2, radiusM: 200, label: nil
        )
        XCTAssertNil(body["label"])
        let alsoEmpty = APIClient.privacyZoneBody(
            latitude: 1, longitude: 2, radiusM: 200, label: ""
        )
        XCTAssertNil(alsoEmpty["label"])
    }

    func testUploadAndLaterEditBodiesCarryTheCompleteRidePrivacySnapshot() {
        let publication = RidePublicationSettings(
            visibility: .onlyYou,
            mapVisibility: .hideStartEnd,
            mapHideStartM: 400,
            mapHideEndM: 800
        )
        let upload = APIClient.uploadInitBody(
            fileType: "gpx",
            fileHash: String(repeating: "a", count: 64),
            fileSize: 1_024,
            clientRequestId: "11111111-1111-4111-8111-111111111111",
            parserVersion: 1,
            preliminaryRideHash: String(repeating: "b", count: 64),
            publication: publication
        )
        let edit = APIClient.ridePrivacyBody(publication)

        for body in [upload, edit] {
            XCTAssertEqual(body["visibility"] as? String, "private")
            XCTAssertEqual(body["map_visibility"] as? String, "hide_start_end")
            XCTAssertEqual(body["map_hide_start_m"] as? Int, 400)
            XCTAssertEqual(body["map_hide_end_m"] as? Int, 800)
        }
    }

    func testHideStartAndEndRequiresVisibleEndpointDistances() {
        let fullMap = RidePublicationSettings(
            visibility: .everyone,
            mapVisibility: .showAll,
            mapHideStartM: 0,
            mapHideEndM: 0
        )
        XCTAssertTrue(fullMap.isValid)
        XCTAssertEqual(fullMap.mapLabel, "Show full map")

        let incomplete = fullMap.changingMapVisibility(.hideStartEnd)
        XCTAssertFalse(incomplete.isValid)
        XCTAssertEqual(incomplete.mapLabel, "Choose endpoint distance")

        let complete = incomplete
            .changingMapHideStartM(200)
            .changingMapHideEndM(400)
        XCTAssertTrue(complete.isValid)
        XCTAssertEqual(complete.mapLabel, "Hide first 200 m and last 400 m")
    }

    func testLegacyStableResumeOmitsEveryPrivacyField() {
        let body = APIClient.uploadInitLegacyResumeBody(
            fileType: "gpx",
            fileHash: String(repeating: "a", count: 64),
            fileSize: 1_024,
            clientRequestId: "11111111-1111-4111-8111-111111111111",
            parserVersion: nil,
            preliminaryRideHash: nil
        )

        XCTAssertEqual(
            body["client_request_id"] as? String,
            "11111111-1111-4111-8111-111111111111"
        )
        XCTAssertNil(body["visibility"])
        XCTAssertNil(body["map_visibility"])
        XCTAssertNil(body["map_hide_start_m"])
        XCTAssertNil(body["map_hide_end_m"])
    }

    @MainActor
    func testSaveRidePrivacyFailsClosedUntilZonesAndDefaultsAreLoaded() async {
        let model = RidePublicationReviewModel()
        let unavailable = PrivacySettings(
            contractVersion: "privacy.v2",
            profileVisibility: "public",
            defaultRideVisibility: .everyone,
            defaultMapVisibility: .hideStartEnd,
            defaultMapHideStartM: 200,
            defaultMapHideEndM: 200,
            defaultsApplyTo: "future_rides",
            privacyZoneCount: 0,
            privacyZonesLoaded: nil,
            rideOverrideMode: "optional",
            protocolPublicFields: []
        )

        await model.load { unavailable }

        XCTAssertNil(model.publication)
        XCTAssertTrue(model.isUnavailable)
    }

    func testPostRideDraftNormalizesCopyAndCoverOrder() throws {
        let first = try RidePhotoSelection(
            id: "11111111-1111-4111-8111-111111111111",
            fileName: "first.jpg",
            mimeType: "image/jpg",
            data: Data("one".utf8)
        )
        let second = try RidePhotoSelection(
            id: "22222222-2222-4222-8222-222222222222",
            fileName: "second.png",
            mimeType: "image/png",
            data: Data("two".utf8)
        )
        let draft = RidePostRideDraft(
            title: "  Morning hills  ",
            notes: "  Clear and cold.  ",
            photos: [second.descriptor, first.descriptor]
        )

        XCTAssertEqual(draft.title, "Morning hills")
        XCTAssertEqual(draft.notes, "Clear and cold.")
        XCTAssertEqual(draft.photos.map(\.id), [second.id, first.id])
        XCTAssertEqual(draft.photos.map(\.sortOrder), [0, 1])
        XCTAssertEqual(draft.photos.map(\.role), ["cover", "photo"])
        XCTAssertEqual(first.mimeType, "image/jpeg")
    }

    func testRideMetadataBodyShipsOnlyAuthoredFields() {
        XCTAssertEqual(
            APIClient.rideMetadataBody(title: "Hill loop", notes: nil) as NSDictionary,
            ["title": "Hill loop"] as NSDictionary
        )
        XCTAssertEqual(
            APIClient.rideMetadataBody(title: "", notes: "") as NSDictionary,
            ["title": "", "description": ""] as NSDictionary
        )
    }

    // MARK: Room model — fail closed, server-declared gating

    @MainActor
    func testRoomLoadsBothHalvesTogether() async {
        let model = PrivacyRoomModel()
        model.fetchSettings = { Self.settingsFixture(visibility: .everyone, zoneCount: 0) }
        model.fetchZones = { PrivacyZonesList(zones: [], maxZones: 5) }
        await model.load()
        guard case let .loaded(settings, zones) = model.state else {
            return XCTFail("expected loaded, got \(model.state)")
        }
        XCTAssertEqual(settings.defaultRideVisibility, .everyone)
        XCTAssertEqual(zones.maxZones, 5)
        XCTAssertTrue(model.canAddZone)
    }

    /// Zones failing while settings succeed must NOT render a room that
    /// silently shows "no zones" — the whole room is unavailable.
    @MainActor
    func testZoneFailureFailsTheWholeRoomClosed() async {
        let model = PrivacyRoomModel()
        model.fetchSettings = { Self.settingsFixture(visibility: .everyone, zoneCount: 2) }
        model.fetchZones = {
            throw APIError.http(
                status: 503, code: nil,
                message: "Privacy settings are temporarily unavailable. Please retry."
            )
        }
        await model.load()
        guard case let .unavailable(message) = model.state else {
            return XCTFail("expected unavailable, got \(model.state)")
        }
        XCTAssertTrue(message.contains("temporarily unavailable"))
        XCTAssertFalse(model.canAddZone)
        XCTAssertNil(model.currentDefaultVisibility)
    }

    /// Add gating uses the server-declared cap, not a compiled constant.
    @MainActor
    func testAddZoneGatingFollowsServerDeclaredCap() async {
        let zones = (0..<3).map { index in
            PrivacyZone(
                id: "z\(index)", latitude: 0, longitude: 0, radiusM: 200,
                label: nil, createdAt: nil, updatedAt: nil
            )
        }
        let model = PrivacyRoomModel()
        model.fetchSettings = { Self.settingsFixture(visibility: .everyone, zoneCount: 3) }
        model.fetchZones = { PrivacyZonesList(zones: zones, maxZones: 3) }
        await model.load()
        XCTAssertFalse(model.canAddZone, "at the server's cap, Add must gate")

        model.fetchZones = { PrivacyZonesList(zones: zones, maxZones: 5) }
        await model.load()
        XCTAssertTrue(model.canAddZone)
    }

    @MainActor
    func testSetDefaultVisibilityAdoptsServerResponse() async {
        let model = PrivacyRoomModel()
        model.fetchSettings = { Self.settingsFixture(visibility: .everyone, zoneCount: 0) }
        model.fetchZones = { PrivacyZonesList(zones: [], maxZones: 5) }
        model.putDefaultVisibility = { requested in
            XCTAssertEqual(requested, .onlyYou)
            return Self.settingsFixture(visibility: .onlyYou, zoneCount: 0)
        }
        await model.load()
        let failure = await model.setDefaultVisibility(.onlyYou)
        XCTAssertNil(failure)
        XCTAssertEqual(model.currentDefaultVisibility, .onlyYou)
    }

    @MainActor
    func testFailedDefaultWriteLeavesPriorTruthStanding() async {
        let model = PrivacyRoomModel()
        model.fetchSettings = { Self.settingsFixture(visibility: .everyone, zoneCount: 0) }
        model.fetchZones = { PrivacyZonesList(zones: [], maxZones: 5) }
        model.putDefaultVisibility = { _ in
            throw APIError.http(status: 503, code: nil, message: "Please retry.")
        }
        await model.load()
        let failure = await model.setDefaultVisibility(.followers)
        XCTAssertEqual(failure, "Please retry.")
        XCTAssertEqual(
            model.currentDefaultVisibility, .everyone,
            "a failed write never moves the rendered default"
        )
    }

    // MARK: Fixtures

    private static func settingsFixture(
        visibility: RideVisibility, zoneCount: Int
    ) -> PrivacySettings {
        PrivacySettings(
            contractVersion: "privacy.v2",
            profileVisibility: "public",
            defaultRideVisibility: visibility,
            defaultMapVisibility: .hideStartEnd,
            defaultMapHideStartM: 200,
            defaultMapHideEndM: 200,
            defaultsApplyTo: "future_rides",
            privacyZoneCount: zoneCount,
            privacyZonesLoaded: true,
            rideOverrideMode: "optional",
            protocolPublicFields: []
        )
    }
}
