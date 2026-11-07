import CoreLocation
import Foundation
import Observation

/// The recording screen's local climb-band engine: canon climbs near the ride
/// are fetched once per area and the rider's position is projected onto their
/// existing ordered centerlines. This is live UI guidance only, never D11
/// traversal adjudication or a protocol-accepted completion.
@MainActor
@Observable
final class ClimbBandModel {
    /// What the band shows during a direction-qualified local band ascent.
    struct ActiveClimb {
        let name: String
        /// 0…1 along the canon centerline.
        var progress: Double
        /// Live grade (percent) at the rider's position on the canon profile.
        var gradePct: Double?
        /// Seconds since the local band candidate entered.
        var elapsedS: TimeInterval
        /// Seconds ahead (negative) or behind (positive) the rider's PR pace.
        /// nil when the rider holds no time on this climb's leaderboard.
        var deltaVsPRSeconds: Double?
        /// The climb's canon shape, for drawing the rider onto it. Render-only.
        var profile: [ElevationProfilePoint]
        /// Meters along the canon length at the rider's position.
        var progressM: Double
    }

    private(set) var active: ActiveClimb?

    // MARK: Canon tracks

    private struct CanonTrack {
        let id: String
        let name: String
        let coordinates: [CLLocationCoordinate2D]
        /// Cumulative meters at each coordinate.
        let cumulative: [Double]
        /// Geometry length of the ordered response coordinates. Direction and
        /// endpoint progress use this so the final vertex is exactly 1.0.
        let centerlineLengthM: Double
        /// Canon-reported length retained for profile and PR projection.
        let lengthM: Double
        let profile: [ElevationProfilePoint]
        let prTimeS: Double?
    }

    private var tracks: [CanonTrack] = []
    private var fetchedCenter: CLLocationCoordinate2D?
    private var isFetching = false

    /// Sole owner of local band lifecycle and its per-ascent completions. The
    /// model does not mirror a per-fix history array.
    @ObservationIgnored private var lifecycle = LiveClimbBandLifecycle()
    @ObservationIgnored private var projectionCursor = LiveClimbBandProjectionCursor()

    /// Half-size of the fetched box in degrees (~8 km of latitude).
    private static let boxRadiusDeg = 0.075
    /// Refetch when the rider moves this far from the fetched center.
    private static let refetchM: Double = 5_000

    // MARK: Feeding

    /// Call on each accepted GPS fix while recording.
    func update(location: CLLocation) {
        maintainCanonArea(around: location.coordinate)
        guard !tracks.isEmpty else { return }
        if
            let trackedClimbID = lifecycle.trackedClimbID,
            let index = tracks.firstIndex(where: { $0.id == trackedClimbID })
        {
            follow(trackAt: index, location: location)
        } else {
            detectEntry(location: location)
        }
    }

    func reset() {
        active = nil
        lifecycle.reset()
        projectionCursor.reset()
    }

    // MARK: Canon area

    private func maintainCanonArea(around coordinate: CLLocationCoordinate2D) {
        if let center = fetchedCenter {
            let moved = CLLocation(latitude: center.latitude, longitude: center.longitude)
                .distance(from: CLLocation(latitude: coordinate.latitude, longitude: coordinate.longitude))
            guard moved > Self.refetchM else { return }
        }
        guard !isFetching else { return }
        isFetching = true
        fetchedCenter = coordinate
        Task {
            await fetchCanon(around: coordinate)
            isFetching = false
        }
    }

    private func fetchCanon(around coordinate: CLLocationCoordinate2D) async {
        let latR = Self.boxRadiusDeg
        let lonR = Self.boxRadiusDeg / max(cos(coordinate.latitude * .pi / 180), 0.2)
        let bbox = String(
            format: "%.5f,%.5f,%.5f,%.5f",
            coordinate.longitude - lonR, coordinate.latitude - latR,
            coordinate.longitude + lonR, coordinate.latitude + latR
        )
        guard let response = try? await APIClient.shared.climbs(bbox: bbox) else { return }

        // The rider's existing leaderboard times, for delta vs PR.
        var prByVaultId: [Int: Double] = [:]
        if let positions = try? await APIClient.shared.myLeaderboardPositions().positions {
            for position in positions {
                if let best = position.bestTimeSeconds { prByVaultId[position.vaultId] = best }
            }
        }

        var built: [CanonTrack] = []
        for climb in response.climbs ?? [] {
            let coords = RouteGeometry.coordinates(from: climb.routePreview)
            guard coords.count >= 2 else { continue }
            var cumulative: [Double] = [0]
            cumulative.reserveCapacity(coords.count)
            for i in 1..<coords.count {
                let step = CLLocation(latitude: coords[i - 1].latitude, longitude: coords[i - 1].longitude)
                    .distance(from: CLLocation(latitude: coords[i].latitude, longitude: coords[i].longitude))
                cumulative.append(cumulative[i - 1] + step)
            }
            let centerlineLength = cumulative.last ?? 0
            let length = climb.lengthM ?? centerlineLength
            guard centerlineLength > 0, length > 50 else { continue }
            let vaultId = climb.vaultEconomy?.vaultId ?? climb.vaultId
            built.append(
                CanonTrack(
                    id: climb.id,
                    name: climb.name ?? "Climb",
                    coordinates: coords,
                    cumulative: cumulative,
                    centerlineLengthM: centerlineLength,
                    lengthM: length,
                    profile: climb.elevationProfile ?? [],
                    prTimeS: vaultId.flatMap { prByVaultId[$0] }
                )
            )
        }
        tracks = built
        let retiredUnavailableBand = projectionCursor.applySuccessfulCanonReplacement(
            availableClimbIDs: Set(built.map(\.id)),
            lifecycle: &lifecycle
        )
        if retiredUnavailableBand || lifecycle.trackedClimbID == nil {
            active = nil
        }
    }

    // MARK: Recognition

    private func detectEntry(location: CLLocation) {
        for track in tracks {
            let (nearIndex, distance) = nearestVertex(on: track, to: location.coordinate)
            lifecycle.observe(
                LiveClimbBandSample(
                    climbID: track.id,
                    progress: normalizedProgress(on: track, at: nearIndex),
                    distanceFromCenterlineM: distance,
                    distanceFromFinishM: distanceFromFinish(
                        on: track,
                        to: location.coordinate
                    ),
                    capturedAt: location.timestamp
                )
            )
            if lifecycle.trackedClimbID == track.id {
                projectionCursor.record(nearIndex)
                renderLifecycle(on: track)
                return
            }
        }
    }

    private func follow(trackAt index: Int, location: CLLocation) {
        let track = tracks[index]
        let (nearIndex, distance) = nearestVertex(
            on: track, to: location.coordinate,
            searchFrom: max(projectionCursor.lastNearIndex - 5, 0)
        )

        lifecycle.observe(
            LiveClimbBandSample(
                climbID: track.id,
                progress: normalizedProgress(on: track, at: nearIndex),
                distanceFromCenterlineM: distance,
                distanceFromFinishM: distanceFromFinish(
                    on: track,
                    to: location.coordinate
                ),
                capturedAt: location.timestamp
            )
        )
        if distance <= lifecycle.policy.exitToleranceM {
            projectionCursor.record(nearIndex)
        }
        renderLifecycle(on: track)
    }

    private func renderLifecycle(on track: CanonTrack) {
        guard let bandState = lifecycle.active else {
            active = nil
            return
        }
        let progress = bandState.progress
        let progressM = progress * track.lengthM
        let elapsed = max(0, bandState.capturedAt.timeIntervalSince(bandState.startedAt))

        var delta: Double?
        if let pr = track.prTimeS, progress > 0.02 {
            delta = elapsed - pr * progress
        }

        active = ActiveClimb(
            name: track.name,
            progress: progress,
            gradePct: grade(on: track, atMeters: progressM),
            elapsedS: elapsed,
            deltaVsPRSeconds: delta,
            profile: track.profile,
            progressM: progressM
        )
    }

    private func normalizedProgress(on track: CanonTrack, at index: Int) -> Double {
        min(max(track.cumulative[index] / track.centerlineLengthM, 0), 1)
    }

    private func distanceFromFinish(
        on track: CanonTrack,
        to coordinate: CLLocationCoordinate2D
    ) -> Double {
        guard let finish = track.coordinates.last else { return .infinity }
        return CLLocation(latitude: coordinate.latitude, longitude: coordinate.longitude)
            .distance(
                from: CLLocation(latitude: finish.latitude, longitude: finish.longitude)
            )
    }

    private func nearestVertex(
        on track: CanonTrack,
        to coordinate: CLLocationCoordinate2D,
        searchFrom: Int = 0
    ) -> (index: Int, distanceM: Double) {
        let here = CLLocation(latitude: coordinate.latitude, longitude: coordinate.longitude)
        var best = (index: searchFrom, distanceM: Double.greatestFiniteMagnitude)
        for i in searchFrom..<track.coordinates.count {
            let vertex = CLLocation(
                latitude: track.coordinates[i].latitude, longitude: track.coordinates[i].longitude
            )
            let d = here.distance(from: vertex)
            if d < best.distanceM { best = (i, d) }
        }
        return best
    }

    /// Live grade from the canon profile: slope over a ~30 m window around
    /// the rider's position. Canon data, no smoothing beyond the window.
    private func grade(on track: CanonTrack, atMeters m: Double) -> Double? {
        let profile = track.profile
        guard profile.count >= 2 else { return nil }
        let lower = m - 15
        let upper = m + 15
        var start: ElevationProfilePoint?
        var end: ElevationProfilePoint?
        for point in profile {
            if point.distanceM <= lower { start = point }
            if point.distanceM >= upper { end = point; break }
        }
        let a = start ?? profile[0]
        let b = end ?? profile[profile.count - 1]
        let run = b.distanceM - a.distanceM
        guard run > 5 else { return nil }
        return (b.elevationM - a.elevationM) / run * 100
    }
}
