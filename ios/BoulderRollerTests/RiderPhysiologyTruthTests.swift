import XCTest
@testable import BoulderRoller

final class RiderPhysiologyTruthTests: XCTestCase {
    private func defaults() -> UserDefaults {
        let suite = "RiderPhysiologyTruthTests-\(UUID().uuidString)"
        return UserDefaults(suiteName: suite)!
    }

    func testWeightStartsAbsentAndRoundTripsWithManualProvenance() {
        let defaults = defaults()
        XCTAssertNil(RiderPhysiologyStore.load(riderID: "rider", defaults: defaults).weightKg)

        XCTAssertTrue(
            RiderPhysiologyStore.setWeight(
                kg: 81.44,
                riderID: "rider",
                defaults: defaults
            )
        )
        let stored = RiderPhysiologyStore.load(riderID: "rider", defaults: defaults)
        XCTAssertEqual(stored.weightKg, 81.4)
        XCTAssertEqual(stored.weightSource, .manual)

        RiderPhysiologyStore.clearWeight(riderID: "rider", defaults: defaults)
        XCTAssertNil(RiderPhysiologyStore.load(riderID: "rider", defaults: defaults).weightKg)
    }

    func testWeightBoundsFailClosed() {
        let defaults = defaults()
        XCTAssertFalse(RiderPhysiologyStore.setWeight(kg: 29.9, riderID: "r", defaults: defaults))
        XCTAssertFalse(RiderPhysiologyStore.setWeight(kg: 200.1, riderID: "r", defaults: defaults))
        XCTAssertTrue(RiderPhysiologyStore.setWeight(kg: 30, riderID: "r", defaults: defaults))
        XCTAssertTrue(RiderPhysiologyStore.setWeight(kg: 200, riderID: "r", defaults: defaults))
    }

    func testServerWeightFillsOnlyAnEmptyLocalField() {
        let defaults = defaults()
        RiderPhysiologyStore.adoptServerWeight(
            weightKg: 72.5,
            weightSource: "derived",
            riderID: "rider",
            defaults: defaults
        )
        XCTAssertEqual(
            RiderPhysiologyStore.load(riderID: "rider", defaults: defaults).weightKg,
            72.5
        )

        RiderPhysiologyStore.setWeight(kg: 80, riderID: "rider", defaults: defaults)
        RiderPhysiologyStore.adoptServerWeight(
            weightKg: 70,
            weightSource: "manual",
            riderID: "rider",
            defaults: defaults
        )
        XCTAssertEqual(
            RiderPhysiologyStore.load(riderID: "rider", defaults: defaults).weightKg,
            80
        )
    }

    func testWeightUpdateBodyContainsOnlyWeight() {
        let body = APIClient.physiologyUpdateBody(weightKg: .some(72.5))
        XCTAssertEqual(body.count, 1)
        XCTAssertEqual(body["weight_kg"] as? Double, 72.5)

        let clear = APIClient.physiologyUpdateBody(weightKg: .some(nil))
        XCTAssertTrue(clear["weight_kg"] is NSNull)
    }
}
