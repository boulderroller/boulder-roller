import Foundation

// Codable mirrors of the production privacy contracts (backend
// `app/routes/privacy.py` + `app/services/ride_privacy.py`). The server is
// the only policy engine: zones project other viewers' reads server-side,
// the owner always receives the full trace, and an unavailable contract is
// rendered unavailable — never guessed into a less-private shape.

// MARK: - Ride visibility (audience)

/// The per-ride audience contract: exactly the backend's three values.
/// Rider-facing labels are the Strava-shaped system vocabulary ratified with
/// the joer2 exposure decision ("copy Strava's privacy pattern",
/// 2026-08-02): Everyone / Followers / Only you.
enum RideVisibility: String, Codable, CaseIterable, Sendable {
    case everyone = "public"
    case followers
    case onlyYou = "private"

    var label: String {
        switch self {
        case .everyone: return "Everyone"
        case .followers: return "Followers"
        case .onlyYou: return "Only you"
        }
    }
}

/// Map projection modes for shared rides (`ride_privacy.MapVisibility`).
/// Values are wire-exact; `convertFromSnakeCase` rewrites keys, not values.
enum RideMapVisibility: String, Codable, CaseIterable, Sendable {
    case showAll = "show_all"
    case hideStartEnd = "hide_start_end"
    case hideEntire = "hide_entire"

    var label: String {
        switch self {
        case .showAll: return "Show full map"
        case .hideStartEnd: return "Hide start and end"
        case .hideEntire: return "Hide entire map"
        }
    }
}

/// One complete, explicit publication decision for a ride. Upload creation
/// and later owner edits use this same four-field value so audience and route
/// exposure can never drift apart or fall back independently.
struct RidePublicationSettings: Codable, Equatable, Sendable {
    let visibility: RideVisibility
    let mapVisibility: RideMapVisibility
    let mapHideStartM: Int
    let mapHideEndM: Int

    private static let allowedHideDistances = Set([0, 200, 400, 800, 1600])

    var isValid: Bool {
        guard Self.allowedHideDistances.contains(mapHideStartM),
              Self.allowedHideDistances.contains(mapHideEndM)
        else { return false }
        if mapVisibility == .hideStartEnd {
            return mapHideStartM > 0 && mapHideEndM > 0
        }
        return true
    }

    init(
        visibility: RideVisibility,
        mapVisibility: RideMapVisibility,
        mapHideStartM: Int,
        mapHideEndM: Int
    ) {
        self.visibility = visibility
        self.mapVisibility = mapVisibility
        self.mapHideStartM = mapHideStartM
        self.mapHideEndM = mapHideEndM
    }

    init(settings: PrivacySettings) {
        self.init(
            visibility: settings.defaultRideVisibility,
            mapVisibility: settings.defaultMapVisibility,
            mapHideStartM: settings.defaultMapHideStartM,
            mapHideEndM: settings.defaultMapHideEndM
        )
    }

    init?(state: RidePrivacyState) {
        guard let mapVisibility = state.mapVisibility,
              let mapHideStartM = state.mapHideStartM,
              let mapHideEndM = state.mapHideEndM
        else { return nil }
        self.init(
            visibility: state.visibility,
            mapVisibility: mapVisibility,
            mapHideStartM: mapHideStartM,
            mapHideEndM: mapHideEndM
        )
        guard isValid else { return nil }
    }

    func changingVisibility(_ visibility: RideVisibility) -> Self {
        Self(
            visibility: visibility,
            mapVisibility: mapVisibility,
            mapHideStartM: mapHideStartM,
            mapHideEndM: mapHideEndM
        )
    }

    func changingMapVisibility(_ mapVisibility: RideMapVisibility) -> Self {
        Self(
            visibility: visibility,
            mapVisibility: mapVisibility,
            mapHideStartM: mapHideStartM,
            mapHideEndM: mapHideEndM
        )
    }

    func changingMapHideStartM(_ meters: Int) -> Self {
        Self(
            visibility: visibility,
            mapVisibility: mapVisibility,
            mapHideStartM: meters,
            mapHideEndM: mapHideEndM
        )
    }

    func changingMapHideEndM(_ meters: Int) -> Self {
        Self(
            visibility: visibility,
            mapVisibility: mapVisibility,
            mapHideStartM: mapHideStartM,
            mapHideEndM: meters
        )
    }

    var mapLabel: String {
        switch mapVisibility {
        case .showAll:
            return "Show full map"
        case .hideEntire:
            return "Hide entire map"
        case .hideStartEnd:
            guard mapHideStartM > 0, mapHideEndM > 0 else {
                return "Choose endpoint distance"
            }
            if mapHideStartM == mapHideEndM {
                return "Hide first and last \(mapHideStartM) m"
            }
            return "Hide first \(mapHideStartM) m and last \(mapHideEndM) m"
        }
    }
}

// MARK: - The ratified exposure default (single documented constant)

/// The ratified default-exposure contract — bead `boulderroller-v2-joer2`,
/// Tim, 2026-08-02: future rides default to **Everyone** with the **first
/// and last 200 m hidden**; account defaults affect future rides only;
/// Followers and Only-you rides stay out of public climb Leaderboards; a
/// privacy-settings or projection failure blocks publication rather than
/// falling back to public.
///
/// The client never uses this compiled mirror as a fallback. Save Ride loads
/// the rider's complete server settings, shows them, and persists that exact
/// choice before upload. This constant only pins the ratified expectation for
/// contract tests and documentation.
enum ExposureDefaults {
    static let ratifiedDefaultVisibility: RideVisibility = .everyone
    static let ratifiedDefaultMapVisibility: RideMapVisibility = .hideStartEnd
    static let ratifiedDefaultMapHideStartM = 200
    static let ratifiedDefaultMapHideEndM = 200
}

// MARK: - Account privacy settings (GET/PUT /privacy/settings)

/// The quiet set-and-forget defaults row (`privacy.v2`). Wire keys are
/// camelCase (FastAPI serializes this model by alias), which
/// `convertFromSnakeCase` passes through untouched.
struct PrivacySettings: Codable, Sendable {
    let contractVersion: String?
    let profileVisibility: String
    let defaultRideVisibility: RideVisibility
    let defaultMapVisibility: RideMapVisibility
    let defaultMapHideStartM: Int
    let defaultMapHideEndM: Int
    /// Server-declared scope: account defaults reach future rides only.
    let defaultsApplyTo: String?
    let privacyZoneCount: Int
    let privacyZonesLoaded: Bool?
    let rideOverrideMode: String?
    let protocolPublicFields: [String]?
    /// Explicit opt-in only. Older privacy.v2 responses mean sharing is off.
    var shareWkg = false
}

extension PrivacySettings {
    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        contractVersion = try values.decodeIfPresent(String.self, forKey: .contractVersion)
        profileVisibility = try values.decode(String.self, forKey: .profileVisibility)
        defaultRideVisibility = try values.decode(RideVisibility.self, forKey: .defaultRideVisibility)
        defaultMapVisibility = try values.decode(RideMapVisibility.self, forKey: .defaultMapVisibility)
        defaultMapHideStartM = try values.decode(Int.self, forKey: .defaultMapHideStartM)
        defaultMapHideEndM = try values.decode(Int.self, forKey: .defaultMapHideEndM)
        defaultsApplyTo = try values.decodeIfPresent(String.self, forKey: .defaultsApplyTo)
        privacyZoneCount = try values.decode(Int.self, forKey: .privacyZoneCount)
        privacyZonesLoaded = try values.decodeIfPresent(Bool.self, forKey: .privacyZonesLoaded)
        rideOverrideMode = try values.decodeIfPresent(String.self, forKey: .rideOverrideMode)
        protocolPublicFields = try values.decodeIfPresent([String].self, forKey: .protocolPublicFields)
        shareWkg = try values.decodeIfPresent(Bool.self, forKey: .shareWkg) ?? false
    }
}

// MARK: - Privacy zones (GET/POST/PUT/DELETE /privacy/zones)

/// One validated circular privacy zone. The backend accepts only these radii
/// and at most `PrivacyZonesList.maxZones` zones per rider; the client
/// mirrors — never widens — those constraints.
struct PrivacyZone: Codable, Identifiable, Sendable {
    let id: String
    let latitude: Double
    let longitude: Double
    let radiusM: Int
    let label: String?
    let createdAt: String?
    let updatedAt: String?
}

struct PrivacyZonesList: Codable, Sendable {
    let zones: [PrivacyZone]
    /// Server-declared cap (5 today). Rendered gating always uses this
    /// value, never a compiled copy.
    let maxZones: Int
}

/// The backend's exact allowed zone radii
/// (`ALLOWED_PRIVACY_ZONE_RADII_M = {200, 400, 800, 1600}`), in meters.
/// The contract values are the truth; the label follows the rider's units.
/// The ladder was chosen as the imperial fractions (⅛, ¼, ½, 1 mi — each
/// within 1% of its meter value), so a Miles rider sees those names
/// (ratified 2026-08-21); a Kilometers rider sees exact meters.
enum PrivacyZoneRadius: Int, CaseIterable, Sendable {
    case m200 = 200
    case m400 = 400
    case m800 = 800
    case m1600 = 1600

    /// Exact meters — the contract form.
    var label: String {
        "\(rawValue.formatted()) m"
    }

    func label(units: UnitSystem) -> String {
        switch units {
        case .metric:
            return label
        case .imperial:
            let fraction: String
            switch self {
            case .m200: fraction = "⅛"
            case .m400: fraction = "¼"
            case .m800: fraction = "½"
            case .m1600: fraction = "1"
            }
            return "\(fraction) \(units.distanceUnit)"
        }
    }

    /// Backend zone-create label limit (`label ≤ 50`).
    static let maxLabelLength = 50
}

struct PrivacyZoneDeleteResponse: Codable, Sendable {
    let status: String
    let id: String?
}

// MARK: - Per-ride resolved privacy (ride detail / list `privacy` object)

/// The server-resolved visibility decision attached to ride records
/// (`PrivacyState` in backend schemas, camelCase on the wire). Clients render
/// this; they never re-derive policy.
struct RidePrivacyState: Codable, Sendable {
    let visibility: RideVisibility
    let canView: Bool?
    let isOwner: Bool?
    let mapVisibility: RideMapVisibility?
    let mapHideStartM: Int?
    let mapHideEndM: Int?
    let reason: String?
}

/// `PATCH /rides/{id}` acknowledgment (`{"status": "updated", ...}`).
struct RideUpdateAck: Codable, Sendable {
    let status: String
    let rideId: String?
}

// MARK: - Avatar upload (POST /users/me/avatar/init → storage PUT → complete)

/// Signed avatar upload handle. Upload PUTs the image bytes to `signedUrl`
/// (the same Supabase signed-upload mechanics as ride files), then
/// `complete` finalizes; the new avatar exists only after complete returns
/// the refreshed profile — success is never assumed from the storage PUT.
struct AvatarUploadInit: Codable, Sendable {
    let uploadId: String
    let signedUrl: String
    let expiresIn: Int?
}

/// Backend-allowed avatar media contract
/// (`app/avatar_media_contracts.py`): JPEG/PNG/WebP/HEIC/HEIF, ≤ 15 MB.
enum AvatarMediaContract {
    static let maxFileSizeBytes = 15 * 1024 * 1024
    static let allowedMimeTypes: Set<String> = [
        "image/jpeg", "image/png", "image/webp", "image/heic", "image/heif",
    ]

    /// Mirrors the server's normalizer: parameters stripped, lowercased,
    /// `image/jpg` folded into `image/jpeg`.
    static func normalizedMimeType(_ raw: String) -> String {
        let base = raw.split(separator: ";", maxSplits: 1)[0]
            .trimmingCharacters(in: .whitespaces)
            .lowercased()
        return base == "image/jpg" ? "image/jpeg" : base
    }

    static func isAllowed(mimeType: String) -> Bool {
        allowedMimeTypes.contains(normalizedMimeType(mimeType))
    }
}

// MARK: - Profile editing limits (PUT /users/me)

/// Server validation bounds for the ratified editable identity fields
/// (`UserProfileUpdate`): display_name ≤ 50, location ≤ 100, bio ≤ 280.
enum ProfileEditContract {
    static let maxDisplayNameLength = 50
    static let maxLocationLength = 100
    static let maxBioLength = 280
}
