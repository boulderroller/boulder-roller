import Foundation
import XCTest
@testable import BoulderRoller

final class BoulderRolledTests: XCTestCase {
    func testOutsideTopTenNeverGetsTheMarkBeat() throws {
        let data = try reveal(rank: 11)
        XCTAssertNil(data.leaderboardEntry)
    }

    func testProductionCamelCasePRFieldAdmitsTheSameTopTenResult() throws {
        XCTAssertEqual(try reveal(prKey: "isPR").leaderboardEntry?.rank, 3)
    }

    func testDetectorMatchAndCanonIdentityAloneDoNotTriggerReveal() throws {
        XCTAssertTrue(try reveal(authoritative: false).beats.isEmpty)
        let held = try reveal(authoritative: false, held: true)
        XCTAssertEqual(held.beats, [.ledger])
        XCTAssertNil(held.leaderboardEntry)
        XCTAssertNil(held.climbs.first?.isNewBest)
    }

    func testSuppliedZeroTributeIsAnItemizedRow() {
        var data = RideUploadRenderFixtureData.reveal
        data.tributeLines = [.init(patternID: "black", climbName: "Black Rock Road", baseUnits: "0", decimals: 9)]
        XCTAssertEqual(data.itemizedTribute.count, 1)
        XCTAssertEqual(data.itemizedTribute.first?.baseUnits, "0")
    }

    func testTriggerRequiresACountedClimbAndCoinRequiresPositiveUnheldCAL() throws {
        var data = RideUploadRenderFixtureData.reveal
        XCTAssertEqual(data.beats, [.coin, .mark, .ledger])
        data.thresholdEconomyState = "held"
        XCTAssertEqual(data.beats, [.mark, .ledger])
        let empty = RevealData(title: nil, subtitle: "", calEarned: 84, distanceM: nil,
            elevationM: nil, durationS: nil, climbs: [], tributeCal: nil, leaderboardEntry: data.leaderboardEntry)
        XCTAssertEqual(empty.beats, [])
        for cal in [nil, 0, -1] as [Double?] {
            let ordinary = RevealData(title: nil, subtitle: "", calEarned: cal, distanceM: nil,
                elevationM: nil, durationS: nil, climbs: data.climbs, tributeCal: nil, leaderboardEntry: nil)
            XCTAssertEqual(ordinary.beats, [.ledger])
        }
    }

    func testTopTenAndNewBestAreIndependentFromEachOther() throws {
        for rank in [1, 3, 4, 10] {
            XCTAssertEqual(try reveal(rank: rank).leaderboardEntry?.rank, rank)
        }
        for rank in [0, 11, 50] { XCTAssertNil(try reveal(rank: rank).leaderboardEntry) }
        XCTAssertNil(try reveal(rank: 3, isPR: false).leaderboardEntry)
        XCTAssertEqual(try reveal(rank: 11).climbs.first?.isNewBest, true)
        XCTAssertNil(try reveal().leaderboardEntry?.previousBestTimeS)
        XCTAssertNil(try reveal().leaderboardEntry?.neighboringSeats)
    }

    func testAggregateTributeNeverCreatesARowOrChangesTheCoin() throws {
        let data = try reveal()
        XCTAssertEqual(data.tributeCal, 14)
        XCTAssertTrue(data.itemizedTribute.isEmpty)
        let fixture = RideUploadRenderFixtureData.reveal
        XCTAssertEqual(fixture.itemizedTribute.map(\.baseUnits), ["6000000000", "3000000000", "5000000000"])
        XCTAssertEqual(fixture.coinFigure(completedSpans: 0), 0)
        XCTAssertEqual(fixture.coinFigure(completedSpans: 1), 28)
        XCTAssertEqual(fixture.coinFigure(completedSpans: 3), 84)
        XCTAssertEqual(fixture.coinFigure(completedSpans: 100), 84)
    }

    func testTributeJoinsByPatternIDAndPreservesExactUnits() throws {
        let decoder = JSONDecoder()
        let itemization = try decoder.decode(CalItemization.self, from: Data("""
        {"calDecimals":9,"climbs":[
          {"patternId":"black","climbName":"Black Rock Road","calTributeBaseUnits":"3000000001"},
          {"patternId":"unknown","climbName":"Unknown","calTributeBaseUnits":"9000000000"},
          {"patternId":"black","calTributeBaseUnits":"-1"}]}
        """.utf8))
        let patterns = try decoder.decode(PatternsPayload.self, from: Data("""
        {"climbPatterns":[{"id":"black","name":"Black Rock Road","climbId":"canon-black"}]}
        """.utf8))
        let lines = RevealData.tribute(itemization: itemization, climbs: patterns.climbPatterns!)
        XCTAssertEqual(lines?.count, 1)
        XCTAssertEqual(lines?.first?.baseUnits, "3000000001")
        XCTAssertNil(RevealData.tribute(itemization: nil, climbs: patterns.climbPatterns!))
    }

    func testDrainSettlesSpansAndChecksBeforeTributeAndVerification() {
        var drain = RevealDrain(climbCount: 3, tributeCount: 2)
        XCTAssertEqual(drain.events, [.tick(0), .settleClimb(0), .tick(1), .settleClimb(1),
            .tick(2), .settleClimb(2), .settleTribute(0), .settleTribute(1), .verification])
        for index in 0..<3 {
            XCTAssertFalse(drain.isStone)
            XCTAssertFalse(drain.settledClimb(index))
            drain.advance()
            XCTAssertTrue(drain.ticked(index))
            XCTAssertFalse(drain.settledClimb(index))
            drain.advance()
            XCTAssertTrue(drain.settledClimb(index))
            XCTAssertFalse(drain.settledTribute(0))
        }
        drain.advance()
        XCTAssertTrue(drain.settledTribute(0))
        XCTAssertFalse(drain.settledTribute(1))
        drain.advance()
        XCTAssertFalse(drain.showsVerification)
        drain.advance()
        XCTAssertTrue(drain.isStone)
        XCTAssertTrue(drain.showsVerification)
        drain.advance()
        XCTAssertTrue(drain.isStone)
    }

    func testReduceMotionDrainFinishesEveryGoldSlot() {
        var drain = RevealDrain(climbCount: 8, tributeCount: 8)
        drain.finish()
        XCTAssertTrue(drain.isStone)
        for i in 0..<8 {
            XCTAssertTrue(drain.settledClimb(i))
            XCTAssertTrue(drain.settledTribute(i))
        }
    }

    func testLegacyQueuedRevealDecodesWithoutNewFieldsOrInventingTribute() throws {
        let data = try JSONDecoder().decode(RevealData.self, from: Data("""
        {"subtitle":"","climbs":[{"name":"Climb","isLeaderboardEntry":true}],"tributeCal":31,
         "leaderboardEntry":{"rank":3,"climbName":"Climb","wasTimeS":86}}
        """.utf8))
        XCTAssertEqual(data.beats, [.mark, .ledger])
        XCTAssertNil(data.spine)
        XCTAssertTrue(data.itemizedTribute.isEmpty)
        XCTAssertNil(data.leaderboardEntry?.previousBestTimeS)
        XCTAssertNil(data.climbs.first?.isNewBest)
    }

    func testSpineClipsTheSameLineAtTheExactSpanEnds() {
        let data = RideSpineData(runs: [[.init(distanceM: 0, elevationM: 10),
            .init(distanceM: 100, elevationM: 110)]], spans: [])
        XCTAssertEqual(data.section(.init(startDistanceM: 25, endDistanceM: 75), in: data.runs[0]),
            [.init(distanceM: 25, elevationM: 35), .init(distanceM: 75, elevationM: 85)])
    }

    private func reveal(rank: Int = 3, isPR: Bool = true, prKey: String = "is_pr", authoritative: Bool = true, held: Bool = false) throws -> RevealData {
        let job = RideUploadRenderFixtureData.job(phase: .processing)
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let status = try decoder.decode(RideStatus.self, from: Data("""
        {"rideId":"\(job.id)","status":"completed","processingStage":"completed",
         "attestationStatus":"attested","canonicalMatch":true,"calEarned":84}
        """.utf8))
        let detail = try decoder.decode(RideDetailResponse.self, from: Data("""
        {"ride":{"id":"\(job.id)","title":"In the bag","startedAt":"2026-09-06T13:07:00Z",
         "status":"completed","isOwner":true,"calEarned":84,"tributableCal":14,
         "thresholdEconomyState":"\(held ? "held" : "counted")"}}
        """.utf8))
        let patterns = try decoder.decode(PatternsResponse.self, from: Data("""
        {"rideId":"\(job.id)","patterns":{"climbPatterns":[
          {"id":"black-rock","climbId":"black-rock","name":"Black Rock Road","durationS":82,"startOffsetS":100,"endOffsetS":182,
           "vaultMatch":{\(authoritative ? "\"vaultId\":3," : "")"vaultClimbId":"black-rock","yourRank":\(rank),"yourTime":82,"\(prKey)":\(isPR)}}]}}
        """.utf8))
        return try LiveRideRevealBuilder().build(job: job, status: status, detail: detail, patterns: patterns)
    }
}
