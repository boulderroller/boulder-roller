import XCTest
@testable import BoulderRoller

final class HiddenRouteTests: XCTestCase {
    private func decode(_ rows: String) throws -> GpsResponse {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(GpsResponse.self, from: Data("{\"gps_points\": [\(rows)]}".utf8))
    }
    private let hidden = #"{"latitude":null,"longitude":null,"elevation_m":null,"elevation_corrected_m":null,"timestamp":null,"distance_m":200,"redacted":true}"#
    private func visible(_ i: Int, extra: String = "") -> String {
        "{\"latitude\":40.0,\"longitude\":\(-75.0 + Double(i) * 0.0001),\"timestamp\":\(1000 + i),\"distance_m\":\(i * 10),\"elevation_m\":20\(extra)}"
    }
    func testHiddenEndsDecodeAndPreserveVisibleRoute() throws {
        let gps = try decode([hidden, visible(1), visible(2), hidden].joined(separator: ","))
        XCTAssertEqual(gps.gpsPoints.count, 4)
        XCTAssertNil(gps.gpsPoints.first?.elevationM)
        XCTAssertNil(gps.gpsPoints.first?.timestamp)
        XCTAssertEqual(RouteGeometry.fragments(from: gps).map(\.count), [2])
    }
    func testExplicitRedactionBreaksRouteAndReliefEvenWithCoordinates() throws {
        let gps = try decode([visible(0), visible(1), visible(2, extra: ",\"redacted\":true"), visible(3), visible(4)].joined(separator: ","))
        XCTAssertEqual(RouteGeometry.fragments(from: gps).map(\.count), [2, 2])
        XCTAssertEqual(ReliefChart.elevationSegments(points: gps.gpsPoints).map(\.count), [2, 2])
    }
    func testNullCoordinateBreaksRouteAndNoMapHasNoGeometry() throws {
        let gps = try decode([visible(0), visible(1), hidden, visible(3), visible(4)].joined(separator: ","))
        XCTAssertEqual(RouteGeometry.fragments(from: gps).map(\.count), [2, 2])
        let noMap = try decode([hidden, hidden].joined(separator: ","))
        XCTAssertTrue(RouteGeometry.fragments(from: noMap).isEmpty)
        XCTAssertTrue(ReliefChart.elevationSegments(points: noMap.gpsPoints).isEmpty)
    }
    func testMissingSingleCoordinateIsAGapWithoutRedactedFlag() throws {
        let missing = #"{"latitude":null,"longitude":-75,"elevation_m":99,"timestamp":1002,"distance_m":20}"#
        let gps = try decode([visible(0), visible(1), missing, visible(3), visible(4)].joined(separator: ","))
        XCTAssertEqual(RouteGeometry.fragments(from: gps).map(\.count), [2, 2])
        XCTAssertEqual(ReliefChart.elevationSegments(points: gps.gpsPoints).map(\.count), [2, 2])
    }
    func testRedactionSurvivesCodableRoundTrip() throws {
        let gps = try decode([visible(0), visible(1), visible(2, extra: ",\"redacted\":true"), visible(3), visible(4)].joined(separator: ","))
        let restored = try JSONDecoder().decode(GpsResponse.self, from: JSONEncoder().encode(gps))
        XCTAssertEqual(RouteGeometry.fragments(from: restored).map(\.count), [2, 2])
    }

}
