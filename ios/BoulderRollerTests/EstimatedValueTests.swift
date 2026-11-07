import SwiftUI
import XCTest
@testable import BoulderRoller

final class EstimatedValueTests: XCTestCase {
    private func disclosure(_ json: String) throws -> EstimatePresentation {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(RideTrainingMetrics.self, from: Data(json.utf8))
            .loadDisclosure(value: 82)
    }

    func testOnlyExplicitAPIFlagsMarkLoad() throws {
        for json in ["{}", #"{"load_estimate":false}"#,
                     #"{"estimates":{"load":{"value":82,"estimate":false,"basis":"hrss"}}}"#] {
            let presentation = try disclosure(json)
            XCTAssertFalse(presentation.isEstimate)
            XCTAssertEqual(presentation.accessibilityLabel, "82")
        }
        for json in [#"{"load_estimate":true}"#,
                     #"{"estimates":{"load":{"value":82,"estimate":true,"basis":"power"}}}"#] {
            let presentation = try disclosure(json)
            XCTAssertTrue(presentation.isEstimate)
            XCTAssertEqual(presentation.hasDetails, !presentation.copyLines.isEmpty)
            XCTAssertEqual(presentation.accessibilityLabel, "Estimated 82")
        }
    }

    func testAccessibilitySpeaksUnitsWithoutTheMark() {
        for (unit, spoken) in [("W", "watts"), ("bpm", "beats per minute"), ("kcal", "kilocalories")] {
            let presentation = EstimatePresentation(value: 251, estimate: true) {
                "\(Format.number($0, places: Precision.power)) \(unit)"
            }
            XCTAssertEqual(presentation.accessibilityLabel, "Estimated 251 \(spoken)")
            XCTAssertFalse(presentation.accessibilityLabel.contains("≈"))
        }
    }

    func testRangeUsesTheSameFormatterAndOnlyOneUnit() {
        let format: (Double) -> String = { "\(Format.number($0, places: Precision.power)) W" }
        let presentation = EstimatePresentation(value: 251.4, estimate: true, range: [238.4, 264.7], format: format)
        XCTAssertEqual(presentation.formattedValue, format(251.4))
        XCTAssertEqual(presentation.formattedRange, "238–265 W")
        XCTAssertTrue(presentation.hasDetails)
        let decimal = EstimatePresentation(value: 25.14, estimate: true, range: [23.84, 26.47]) {
            Format.number($0, places: Precision.distance)
        }
        XCTAssertEqual(decimal.formattedValue, Format.number(25.14, places: Precision.distance))
        XCTAssertEqual(decimal.formattedRange, "\(Format.number(23.84, places: Precision.distance))–\(Format.number(26.47, places: Precision.distance))")
    }

    func testLoadRetainsItsFormatterAndSuppliedRange() throws {
        let presentation = try disclosure(#"{"load_estimate":true,"estimates":{"load":{"value":82,"estimate":true,"basis":"hrss","range":[70.2,94.8]}}}"#)
        XCTAssertEqual(presentation.formattedValue, Format.amount(82))
        XCTAssertEqual(presentation.formattedRange, "\(Format.amount(70.2))–\(Format.amount(94.8))")
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let pending = try decoder.decode(RideTrainingMetrics.self, from: Data(#"{"load_estimate":true}"#.utf8))
            .loadDisclosure(value: 82, isPending: true)
        XCTAssertEqual(pending.accessibilityLabel, "Estimated 82 · Pending")
    }

    func testOpenEstimateRangesDoNotPreventRideDecoding() throws {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        for range in ["[238,null]", "[null,264]", "[null,null]"] {
            let json = """
            {"id":"open-range-ride","started_at":"2026-10-13T12:00:00Z","tss":82,
             "training_metrics":{"load_estimate":true,
              "threshold":{"value":251,"estimate":true,"basis":"threshold_cp_3_7_15_v1","range":\(range)},
              "estimates":{"load":{"value":82,"estimate":true,"basis":"power","range":\(range)}}}}
            """
            let ride = try decoder.decode(Ride.self, from: Data(json.utf8))
            let training = try XCTUnwrap(ride.trainingMetrics)
            let load = training.loadDisclosure(value: try XCTUnwrap(ride.tss))
            XCTAssertEqual(load.accessibilityLabel, "Estimated 82")
            XCTAssertNil(load.formattedRange)
            XCTAssertEqual(load.hasDetails, !load.copyLines.isEmpty)
            let threshold = try XCTUnwrap(training.threshold)
            let presentation = EstimatePresentation(value: threshold.value, estimate: threshold.estimate,
                basis: threshold.basis, range: threshold.range, format: { Format.threshold(Int($0)) })
            XCTAssertNil(presentation.formattedRange)
            XCTAssertEqual(presentation.hasDetails, !presentation.copyLines.isEmpty)
        }
    }

    func testUnknownProvenanceAndInvalidRangesStayAbsent() throws {
        let legacy = try disclosure(#"{"load_estimate":true}"#)
        XCTAssertNil(legacy.formattedRange)
        XCTAssertTrue(legacy.copyLines.isEmpty)
        XCTAssertFalse(legacy.hasDetails)
        for range: [Double?]? in [nil, [], [1], [1, 2, 3], [nil, 2], [1, nil], [.nan, 2], [1, .infinity]] {
            let presentation = EstimatePresentation(value: 82, estimate: true, range: range, format: { Format.amount($0) })
            XCTAssertNil(presentation.formattedRange)
            XCTAssertFalse(presentation.hasDetails)
        }
    }

    func testMissingAndUnwrittenCopyRendersNothing() {
        XCTAssertEqual(EstimateCopy.lines(basis: nil), [])
        XCTAssertEqual(EstimateCopy.lines(basis: "unknown-basis"), [])
        XCTAssertEqual(EstimateCopy.visibleLines(["", "  \n", "TIM:", "[TIM: pending words]", " TIM: "]), [])
        XCTAssertEqual(EstimateCopy.visibleLines(["  First line\n", "Second line", "TIM:"]), ["First line", "Second line"])
    }

    @MainActor
    func testMeasuredLabelRendersExactlyAsBeforeAndOnlyEstimateAddsMark() throws {
        let original = StatValueText(value: "251", unit: "W")
        let measured = EstimatedValue(presentation: EstimatePresentation(value: 251, estimate: false, format: { Format.threshold(Int($0)) })) {
            original
        }
        let estimated = EstimatedValue(presentation: EstimatePresentation(value: 251, estimate: true, format: { Format.threshold(Int($0)) })) {
            original
        }
        func render<V: View>(_ view: V) throws -> UIImage {
            try XCTUnwrap(ImageRenderer(content: view.padding(8).background(Theme.screen)).uiImage)
        }
        let old = try render(original)
        let exact = try render(measured)
        let marked = try render(estimated)
        XCTAssertEqual(exact.size, old.size)
        XCTAssertEqual(exact.pngData(), old.pngData())
        XCTAssertGreaterThan(marked.size.width, exact.size.width)
        XCTAssertEqual(marked.size.height, exact.size.height)
    }
}
