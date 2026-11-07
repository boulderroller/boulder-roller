import CoreLocation
import Foundation

/// An immutable observation from Core Location. Filtering may reject an
/// observation or smooth its scalar speed/course values, but it never edits
/// latitude or longitude: the route is always a subset of recorded positions.
struct GPSObservation: Codable, Equatable, Sendable {
    let timestamp: Date
    let latitude: Double
    let longitude: Double
    let horizontalAccuracyM: Double
    let speedMps: Double?
    let speedAccuracyMps: Double?
    let courseDegrees: Double?

    init(
        timestamp: Date,
        latitude: Double,
        longitude: Double,
        horizontalAccuracyM: Double,
        speedMps: Double?,
        speedAccuracyMps: Double?,
        courseDegrees: Double?
    ) {
        self.timestamp = timestamp
        self.latitude = latitude
        self.longitude = longitude
        self.horizontalAccuracyM = horizontalAccuracyM
        self.speedMps = speedMps.flatMap { $0.isFinite && $0 >= 0 ? $0 : nil }
        self.speedAccuracyMps = speedAccuracyMps.flatMap { $0.isFinite && $0 >= 0 ? $0 : nil }
        self.courseDegrees = courseDegrees.flatMap { $0.isFinite && $0 >= 0 ? $0 : nil }
    }

    init(location: CLLocation) {
        self.init(
            timestamp: location.timestamp,
            latitude: location.coordinate.latitude,
            longitude: location.coordinate.longitude,
            horizontalAccuracyM: location.horizontalAccuracy,
            speedMps: location.speed,
            speedAccuracyMps: location.speedAccuracy,
            courseDegrees: location.course
        )
    }

    var vertex: RouteVertex { RouteVertex(latitude: latitude, longitude: longitude) }
}

struct AcceptedGPSPoint: Equatable {
    let observation: GPSObservation
    let filteredSpeedMps: Double?
    let filteredCourseDegrees: Double?
    let startsNewSegment: Bool
    /// Nil means there is no evidenced adjacent edge (first point or a gap).
    let distanceFromPreviousM: Double?
    /// Portion of the edge remaining after both horizontal-accuracy radii.
    let evidencedDistanceFromPreviousM: Double?
}

struct GPSTruthPolicy: Equatable {
    var maximumHorizontalAccuracyM: Double = 40
    var maximumSpeedAccuracyMps: Double = 2.5
    var gapIntervalS: TimeInterval = 8
    var maximumCredibleSpeedMps: Double = 55
    var scalarWindowSize: Int = 3
}

/// Stateful capture filter. A long outage and an explicit pause boundary both
/// begin a new segment. Short-window speed/course filtering changes display
/// scalars only; coordinates remain the exact accepted observations.
struct GPSTruthPipeline {
    private(set) var accepted: [AcceptedGPSPoint] = []
    private var needsSegmentBreak = false
    private var recentSpeeds: [Double] = []
    private var recentCourses: [Double] = []
    let policy: GPSTruthPolicy

    init(policy: GPSTruthPolicy = GPSTruthPolicy()) {
        self.policy = policy
    }

    var fragments: [[GPSObservation]] {
        var result: [[GPSObservation]] = []
        for point in accepted {
            if point.startsNewSegment || result.isEmpty {
                result.append([point.observation])
            } else {
                result[result.count - 1].append(point.observation)
            }
        }
        return result
    }

    mutating func requireSegmentBreak() {
        needsSegmentBreak = true
        recentSpeeds.removeAll(keepingCapacity: true)
        recentCourses.removeAll(keepingCapacity: true)
    }

    @discardableResult
    mutating func ingest(_ observation: GPSObservation) -> AcceptedGPSPoint? {
        guard isValid(observation) else { return nil }

        let previous = accepted.last?.observation
        var startsNewSegment = previous == nil || needsSegmentBreak
        var edgeDistance: Double?
        var evidencedEdgeDistance: Double?

        if let previous {
            let interval = observation.timestamp.timeIntervalSince(previous.timestamp)
            guard interval > 0 else { return nil }
            if interval > policy.gapIntervalS {
                startsNewSegment = true
            } else if !startsNewSegment {
                let distance = previous.vertex.distance(to: observation.vertex)
                let uncertainty = previous.horizontalAccuracyM + observation.horizontalAccuracyM
                let evidencedDistance = max(0, distance - uncertainty)
                guard evidencedDistance / interval <= policy.maximumCredibleSpeedMps else { return nil }
                edgeDistance = distance
                evidencedEdgeDistance = evidencedDistance
            }
        }

        if startsNewSegment {
            edgeDistance = nil
            recentSpeeds.removeAll(keepingCapacity: true)
            recentCourses.removeAll(keepingCapacity: true)
        }
        needsSegmentBreak = false

        let qualifiedSpeed: Double? = observation.speedMps.flatMap { speed in
            guard
                let accuracy = observation.speedAccuracyMps,
                accuracy <= policy.maximumSpeedAccuracyMps
            else { return nil }
            return speed
        }
        if let qualifiedSpeed {
            append(qualifiedSpeed, to: &recentSpeeds)
        } else {
            // Missing or accuracy-ineligible evidence breaks scalar
            // continuity; a later fix cannot inherit motion across it.
            recentSpeeds.removeAll(keepingCapacity: true)
        }
        if let course = observation.courseDegrees { append(course, to: &recentCourses) }

        let point = AcceptedGPSPoint(
            observation: observation,
            // A historical window cannot make a current missing or
            // accuracy-ineligible speed observation look qualified.
            filteredSpeedMps: qualifiedSpeed == nil ? nil : median(recentSpeeds),
            filteredCourseDegrees: circularMean(recentCourses),
            startsNewSegment: startsNewSegment,
            distanceFromPreviousM: edgeDistance,
            evidencedDistanceFromPreviousM: evidencedEdgeDistance
        )
        accepted.append(point)
        return point
    }

    private func isValid(_ observation: GPSObservation) -> Bool {
        observation.latitude.isFinite
            && observation.longitude.isFinite
            && (-90...90).contains(observation.latitude)
            && (-180...180).contains(observation.longitude)
            && observation.horizontalAccuracyM.isFinite
            && observation.horizontalAccuracyM >= 0
            && observation.horizontalAccuracyM <= policy.maximumHorizontalAccuracyM
    }

    private func append(_ value: Double, to values: inout [Double]) {
        values.append(value)
        if values.count > policy.scalarWindowSize {
            values.removeFirst(values.count - policy.scalarWindowSize)
        }
    }

    private func median(_ values: [Double]) -> Double? {
        guard !values.isEmpty else { return nil }
        let sorted = values.sorted()
        let middle = sorted.count / 2
        if sorted.count.isMultiple(of: 2) {
            return (sorted[middle - 1] + sorted[middle]) / 2
        }
        return sorted[middle]
    }

    private func circularMean(_ values: [Double]) -> Double? {
        guard !values.isEmpty else { return nil }
        let vectors = values.map { degrees -> (Double, Double) in
            let radians = degrees * .pi / 180
            return (sin(radians), cos(radians))
        }
        let sine = vectors.reduce(0) { $0 + $1.0 }
        let cosine = vectors.reduce(0) { $0 + $1.1 }
        guard sine != 0 || cosine != 0 else { return values.last }
        let degrees = atan2(sine, cosine) * 180 / .pi
        return degrees >= 0 ? degrees : degrees + 360
    }
}

struct RouteVertex: Hashable {
    let latitude: Double
    let longitude: Double

    func distance(to other: RouteVertex) -> Double {
        let radiusM = 6_371_008.8
        let lat1 = latitude * .pi / 180
        let lat2 = other.latitude * .pi / 180
        let deltaLat = (other.latitude - latitude) * .pi / 180
        let deltaLon = (other.longitude - longitude) * .pi / 180
        let a = sin(deltaLat / 2) * sin(deltaLat / 2)
            + cos(lat1) * cos(lat2) * sin(deltaLon / 2) * sin(deltaLon / 2)
        return radiusM * 2 * atan2(sqrt(a), sqrt(max(0, 1 - a)))
    }
}

/// Ramer-Douglas-Peucker simplification that only selects original vertices.
/// The tolerance grows when zooming out; it never interpolates a coordinate.
enum ZoomRouteSimplifier {
    static func toleranceMeters(forZoomLevel zoomLevel: Double) -> Double {
        min(24, max(0.5, pow(2, 16 - zoomLevel) * 0.75))
    }

    static func simplify(_ points: [RouteVertex], zoomLevel: Double) -> [RouteVertex] {
        simplify(points, toleranceM: toleranceMeters(forZoomLevel: zoomLevel))
    }

    static func simplify(_ points: [RouteVertex], toleranceM: Double) -> [RouteVertex] {
        guard points.count > 2, toleranceM > 0 else { return points }
        var keep = Set([0, points.count - 1])
        simplify(points, first: 0, last: points.count - 1, toleranceM: toleranceM, keep: &keep)
        return keep.sorted().map { points[$0] }
    }

    private static func simplify(
        _ points: [RouteVertex],
        first: Int,
        last: Int,
        toleranceM: Double,
        keep: inout Set<Int>
    ) {
        guard last > first + 1 else { return }
        var farthestIndex: Int?
        var farthestDistance = 0.0
        for index in (first + 1)..<last {
            let distance = perpendicularDistance(
                points[index], from: points[first], to: points[last]
            )
            if distance > farthestDistance {
                farthestDistance = distance
                farthestIndex = index
            }
        }
        guard let farthestIndex, farthestDistance > toleranceM else { return }
        keep.insert(farthestIndex)
        simplify(points, first: first, last: farthestIndex, toleranceM: toleranceM, keep: &keep)
        simplify(points, first: farthestIndex, last: last, toleranceM: toleranceM, keep: &keep)
    }

    private static func perpendicularDistance(
        _ point: RouteVertex,
        from start: RouteVertex,
        to end: RouteVertex
    ) -> Double {
        let referenceLatitude = (start.latitude + end.latitude + point.latitude) / 3 * .pi / 180
        let metersPerDegreeLatitude = 111_132.92
        let metersPerDegreeLongitude = 111_412.84 * cos(referenceLatitude)
        let sx = start.longitude * metersPerDegreeLongitude
        let sy = start.latitude * metersPerDegreeLatitude
        let ex = end.longitude * metersPerDegreeLongitude
        let ey = end.latitude * metersPerDegreeLatitude
        let px = point.longitude * metersPerDegreeLongitude
        let py = point.latitude * metersPerDegreeLatitude
        let dx = ex - sx
        let dy = ey - sy
        let denominator = dx * dx + dy * dy
        guard denominator > 0 else { return hypot(px - sx, py - sy) }
        let t = min(1, max(0, ((px - sx) * dx + (py - sy) * dy) / denominator))
        return hypot(px - (sx + t * dx), py - (sy + t * dy))
    }
}
