import Foundation

/// The one failure classification (granularity 12): every surface that
/// decides "can Retry work?", "must this wait?", or "is this final?" asks
/// here instead of pattern-matching status codes locally. Copy stays with
/// the surfaces (empty or Tim's); this layer only carries truth.
enum APIFailureClass: Equatable, Sendable {
    /// The request never reached the server — retry is honest.
    case offline
    /// The server said 503; retry is honest, after any stated interval.
    case maintenance(retryAfterS: Double?)
    /// 429 — retry is honest only after the server's stated interval.
    case rateLimited(retryAfterS: Double?)
    /// A 5xx that isn't maintenance — retry is honest.
    case serverError
    /// This build can no longer perform the write. Retrying the same
    /// request is a lie; the remedy is an app update when a path exists.
    case staleClient
    /// The session ended definitively; only sign-in remedies it.
    case notAuthenticated
    /// The server understood and refused (4xx) — retrying unchanged input
    /// is a lie.
    case client
    /// Unexpected shape (decoding, unknown transport) — needs review;
    /// never rendered as success or as fake emptiness.
    case needsReview

    /// Whether an unchanged retry can truthfully be offered.
    var isRetryable: Bool {
        switch self {
        case .offline, .maintenance, .rateLimited, .serverError:
            return true
        case .staleClient, .notAuthenticated, .client, .needsReview:
            return false
        }
    }

    /// Server-stated wait before a retry is honest, when one was given.
    var retryAfterS: Double? {
        switch self {
        case let .maintenance(seconds), let .rateLimited(seconds):
            return seconds
        default:
            return nil
        }
    }

    /// Classify any error the API layer can throw.
    static func classify(_ error: any Error) -> APIFailureClass {
        if let urlError = error as? URLError {
            switch urlError.code {
            case .notConnectedToInternet, .networkConnectionLost, .timedOut,
                 .cannotConnectToHost, .cannotFindHost, .dnsLookupFailed,
                 .dataNotAllowed, .internationalRoamingOff:
                return .offline
            default:
                return .needsReview
            }
        }
        guard let apiError = error as? APIError else { return .needsReview }
        switch apiError {
        case let .maintenance(_, retryAfterS):
            return .maintenance(retryAfterS: retryAfterS)
        case let .rateLimited(_, retryAfterS):
            return .rateLimited(retryAfterS: retryAfterS)
        case .staleClient:
            return .staleClient
        case .notAuthenticated:
            return .notAuthenticated
        case let .http(status, _, _), let .uploadConflict(status, _, _, _, _):
            if (500...599).contains(status) { return .serverError }
            if (400...499).contains(status) { return .client }
            return .needsReview
        case .decoding, .stage1OperationPending:
            return .needsReview
        }
    }
}
