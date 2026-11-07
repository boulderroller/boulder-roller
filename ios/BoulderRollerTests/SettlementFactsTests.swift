import Foundation
import Testing
@testable import BoulderRoller

/// L2.10: settlement facts are exact — base units and decimal strings
/// never pass through binary float, absence stays absent, and the rider's
/// week total is their own receipts, not the vault-wide distribution.
struct SettlementFactsTests {
    private func receipt(_ id: String, amount: String?) -> DistributionReceiptRow {
        DistributionReceiptRow(
            id: id, receiptType: "staker_allocation",
            amount: amount, amountBaseUnits: nil,
            rank: nil, createdAt: nil, txSignature: nil
        )
    }

    // MARK: Exact decimal display

    @Test func exactAmountNeverRoutesThroughFloat() {
        // A value binary float cannot represent at this precision.
        #expect(Format.exactAmount("9007199254740993", decimals: 0)
            == "9,007,199,254,740,993")
        #expect(Format.exactAmount("12.35") == "12.4")
        #expect(Format.exactAmount("60.000000001") == "60")
        #expect(Format.exactAmount("0") == "0")
    }

    @Test func exactAmountRefusesGarbageAndAbsence() {
        #expect(Format.exactAmount(nil) == nil)
        #expect(Format.exactAmount("") == nil)
        #expect(Format.exactAmount("not-a-number") == nil)
    }

    // MARK: The rider's week total

    @Test func riderShareSumsOwnReceiptsExactly() {
        let share = SettlementFacts.riderShare([
            receipt("a", amount: "8.100000001"),
            receipt("b", amount: "4.2"),
        ])
        #expect(share == "12.3")
    }

    @Test func riderShareStaysUnavailableOnAnyUnreadableRow() {
        #expect(SettlementFacts.riderShare(nil) == nil)
        #expect(SettlementFacts.riderShare([]) == nil)
        // One bad row poisons the total — a partial sum would be a lie.
        #expect(SettlementFacts.riderShare([
            receipt("a", amount: "8.1"),
            receipt("b", amount: nil),
        ]) == nil)
        #expect(SettlementFacts.riderShare([
            receipt("a", amount: "8.1"),
            receipt("b", amount: "??"),
        ]) == nil)
    }

    // MARK: The wire contract decodes

    @Test func itemizedGroupDecodesFromCanonicalWireShape() throws {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let json = #"""
        {"distribution_id": "v4a:16:131", "vault_signature": "ab",
         "epoch": 131,
         "total_amount": "60.000000001", "total_amount_base_units": "60000000001",
         "leaderboard_amount": "33.0", "leaderboard_amount_base_units": "33000000000",
         "staker_amount": "16.2", "staker_amount_base_units": "16200000000",
         "local_legend_amount": "1.8", "local_legend_amount_base_units": "1800000000",
         "pol_amount": "6.0", "pol_amount_base_units": "6000000000",
         "protocol_amount": "3.0", "protocol_amount_base_units": "3000000000",
         "distributed_at": "2026-08-17T12:00:00Z", "finalized_at": "",
         "current_carry": {"record_royalty": "0", "stakers": "2.5",
                           "local_legend": "0", "pol": "0", "treasury": "0"},
         "receipts": [{"id": "r1", "receipt_type": "staker_allocation",
                       "amount": "8.1", "amount_base_units": "8100000000",
                       "rank": null, "created_at": "2026-08-17T12:00:05Z"}]}
        """#
        let group = try decoder.decode(DistributionGroup.self, from: Data(json.utf8))
        #expect(group.epoch == 131)
        #expect(group.stakerAmount == "16.2")
        #expect(group.finalizedAt == "")
        #expect(group.currentCarry?.stakers == "2.5")
        #expect(group.receipts?.first?.amount == "8.1")
    }
}
