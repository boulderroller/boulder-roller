import XCTest
import CryptoKit
@testable import BoulderRoller

final class Stage1TransactionFirewallTests: XCTestCase {
    func fixtures() throws -> [[String: Any]] {
        #if SWIFT_PACKAGE
        let bundle = Bundle.module
        #else
        let bundle = Bundle(for: Self.self)
        #endif
        let url = try XCTUnwrap(bundle.url(forResource: "prepared-stage1-transactions", withExtension: "json"))
        return try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [[String: Any]])
    }

    private func hex(_ value: String) -> Data {
        let chars = Array(value)
        return Data(stride(from: 0, to: chars.count, by: 2).map { UInt8(String(chars[$0...($0 + 1)]), radix: 16)! })
    }

    func intent(_ row: [String: Any], wallet: String? = nil) -> BalanceTransactionIntent {
        let value = row["intent"] as! [String: Any]
        func string(_ name: String) -> String { value[name] as! String }
        func uint(_ name: String) -> UInt64 { UInt64(string(name))! }
        func leaf(_ item: [String: Any]) -> Stage1ClaimLeaf {
            Stage1ClaimLeaf(hill: item["hill"] as! String, week: UInt64(item["week"] as! String)!,
                index: UInt32(item["index"] as! Int), amount: UInt64(item["amountBaseUnits"] as! String)!,
                proof: (item["proof"] as! [[String: Any]]).map { Stage1ClaimProof(hash: hex($0["hash"] as! String), sum: UInt128($0["sum"] as! String)!) })
        }
        let action: Stage1TransactionIntent
        switch string("kind") {
        case "stage1_claim_transport":
            let mode = string("mode")
            action = .claimTransport(mode: mode == "create" ? .create : mode == "deactivate" ? .deactivate : .close,
                table: string("lookupTable"), recentSlot: UInt64(value["recentSlot"] as? String ?? "0")!, addresses: value["addresses"] as? [String] ?? [])
        case "stage1_registration": action = .registration
        case "stage1_cancel_pledge": action = .cancelPledge(hill: string("hill"), mint: string("mint"), depositID: uint("depositId"))
        case "stage1_pledge":
            action = .pledge(hill: string("hill"), climb: string("climb"), mint: string("mint"), depositID: uint("depositId"),
                amount: uint("amountBaseUnits"), lockWeeks: UInt16(value["lockWeeks"] as! Int), bonded: string("providerMode") == "bonded",
                backingMints: value["backingMints"] as! [String])
        case "stage1_withdrawal_notice":
            action = .withdrawalNotice(hill: string("hill"), depositID: uint("depositId"), requestID: uint("requestId"), basisLamports: uint("basisLamports"))
        case "stage1_cancel_notice": action = .cancelNotice(depositID: uint("depositId"), requestID: uint("requestId"))
        case "stage1_begin_withdrawal":
            action = .beginWithdrawal(hill: string("hill"), mint: string("mint"), depositID: uint("depositId"), requestID: uint("requestId"), week: uint("week"), refreshRate: value["refreshRate"] as? Bool ?? true)
        case "stage1_complete_withdrawal":
            action = .completeWithdrawal(hill: string("hill"), mint: string("mint"), depositID: uint("depositId"), requestID: uint("requestId"), week: uint("week"), refreshRate: value["refreshRate"] as? Bool ?? true)
        case "stage1_convert_pledge":
            action = .convertPledge(hill: string("hill"), mint: string("mint"), depositID: uint("depositId"), lockWeeks: UInt16(value["lockWeeks"] as! Int), refreshRate: value["refreshRate"] as? Bool ?? true)
        case "stage1_self_claim":
            let leaves = value["claims"] as! [[String: Any]]
            if string("claimType") == "cash" {
                action = .cashClaim(mint: string("mint"), leaves: leaves.map { Stage1CashLeaf(leaf: leaf($0),
                    cap: UInt64($0["capBaseUnits"] as! String)!, frozenAt: Int64($0["frozenAt"] as! String)!, auditHash: hex($0["auditHash"] as! String)) }, single: value["single"] as? Bool ?? false)
            } else {
                action = .dungClaim(leaves: leaves.map { Stage1DungLeaf(leaf: leaf($0), role: UInt8($0["role"] as! Int)) }, single: value["single"] as? Bool ?? false)
            }
        default: fatalError("Unknown offline fixture")
        }
        return .stage1(action, wallet: wallet ?? row["wallet"] as! String)
    }

    private func decode(_ value: String) -> Data? {
        let alphabet = Array("123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz")
        var bytes = [UInt8](repeating: 0, count: 32)
        for character in value {
            guard let digit = alphabet.firstIndex(of: character) else { return nil }
            var carry = digit
            for i in bytes.indices.reversed() { carry += Int(bytes[i]) * 58; bytes[i] = UInt8(carry & 255); carry >>= 8 }
            guard carry == 0 else { return nil }
        }
        return Data(bytes)
    }

    func tables(_ row: [String: Any]) -> [SolanaTransaction.ResolvedLookupTable] {
        guard let lookup = row["lookup"] as? [String: Any] else { return [] }
        return [SolanaTransaction.ResolvedLookupTable(address: decode(lookup["address"] as! String)!,
            authority: decode(row["wallet"] as! String)!, active: true,
            addresses: (lookup["addresses"] as! [String]).map { decode($0)! })]
    }

    // Every account a cash claim derives from its mint, in a fixed order.
    func cashAccounts(_ row: [String: Any], mint: String) throws -> [Data] {
        let key = try Stage1Address.key(mint), wallet = try Stage1Address.key(row["wallet"] as! String)
        let ata = try Stage1Address.derive([wallet, Stage1Address.key(BalanceTransactionFirewall.tokenProgram), key],
                                           program: BalanceTransactionFirewall.associatedTokenProgram)
        let claims = try ((row["intent"] as! [String: Any])["claims"] as! [[String: Any]]).map { leaf in
            try Stage1Address.pda("s1v1_claims", Stage1Address.key(leaf["hill"] as! String), key, Stage1Address.le(UInt64(leaf["week"] as! String)!))
        }
        return try [key, Stage1Address.pda("s1v1_asset", key), Stage1Address.pda("s1v1_earnings", key), ata] + claims
    }

    /// The backend's cash claim in another mint: only its mint-derived accounts move,
    /// as static keys in place or in the independently resolved lookup table.
    func cashClaim(_ row: [String: Any], inMint mint: String) throws -> [String: Any] {
        var result = row, intent = row["intent"] as! [String: Any], prepared = row["prepared"] as! [String: Any]
        let from = try cashAccounts(row, mint: intent["mint"] as! String), to = try cashAccounts(row, mint: mint)
        func swap(_ key: Data) -> Data { from.firstIndex(of: key).map { to[$0] } ?? key }
        var moved = Set<Data>()
        if var lookup = row["lookup"] as? [String: Any] {
            let addresses = (lookup["addresses"] as! [String]).map { decode($0)! }
            moved = Set(addresses.filter { swap($0) != $0 })
            lookup["addresses"] = addresses.map { Base58.encode(swap($0)) }; result["lookup"] = lookup
        } else {
            let original = prepared["transaction"] as! String
            var wire = Data(base64Encoded: original)!
            let keyStart = 1 + Int(wire[0]) * 64 + 4
            for (index, key) in try SolanaTransaction.parseLegacyMessage(transactionB64: original).accountKeys.enumerated() where swap(key) != key {
                wire.replaceSubrange(keyStart + index * 32..<keyStart + index * 32 + 32, with: swap(key)); moved.insert(key)
            }
            prepared["transaction"] = wire.base64EncodedString(); result["prepared"] = prepared
        }
        guard moved == Set(from) else { throw Stage1Error.unavailable }
        intent["mint"] = mint; result["intent"] = intent
        return result
    }

    func testDevnetCityCashMintIsAcceptedForCashClaimsAndNoOtherMintIs() throws {
        let cash = "932CwEMTWHDY1BEkV66DKDgngeEypU3JmybWBu4vMh1e"
        func wire(_ row: [String: Any]) -> String { (row["prepared"] as! [String: Any])["transaction"] as! String }
        for name in ["cash_claim_1", "cash_claim_2", "cash_claim_depth16"] {
            let source = try XCTUnwrap(fixtures().first { $0["name"] as? String == name })
            let row = try cashClaim(source, inMint: cash)
            let other = try cashClaim(source, inMint: "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v")
            XCTAssertNoThrow(try BalanceTransactionFirewall.validate(transactionB64: wire(row), intent: intent(row), lookupTables: tables(row)), name)
            XCTAssertThrowsError(try BalanceTransactionFirewall.validate(transactionB64: wire(row), intent: intent(source), lookupTables: tables(row)), name)
            XCTAssertThrowsError(try BalanceTransactionFirewall.validate(transactionB64: wire(other), intent: intent(other), lookupTables: tables(other)), name)
        }
    }

    func testVersionedLookupResolutionAndEveryProofByteAreRequired() throws {
        for row in try fixtures().filter({ $0["lookup"] != nil }) {
            let wire = (row["prepared"] as! [String: Any])["transaction"] as! String
            let table = tables(row)[0]
            XCTAssertThrowsError(try BalanceTransactionFirewall.validate(transactionB64: wire, intent: intent(row)))
            for index in table.addresses.indices {
                var keys = table.addresses; keys[index][0] ^= 1
                let changed = SolanaTransaction.ResolvedLookupTable(address: table.address, authority: table.authority, active: true, addresses: keys)
                XCTAssertThrowsError(try BalanceTransactionFirewall.validate(transactionB64: wire, intent: intent(row), lookupTables: [changed]))
            }
            let message = try SolanaTransaction.parseStage1Message(transactionB64: wire, owner: table.authority, tables: [table])
            let data = message.instructions.last!.data, original = Data(base64Encoded: wire)!
            let range = try XCTUnwrap(original.range(of: data))
            for index in [0, 7, 8, 40, data.count - 1] {
                var changed = original; changed[range.lowerBound + index] ^= 1
                XCTAssertThrowsError(try BalanceTransactionFirewall.validate(transactionB64: changed.base64EncodedString(), intent: intent(row), lookupTables: [table]))
            }
        }
    }

    func testVersionedSigningPreservesSponsorAndSignsExactMessage() throws {
        let privateKey = try Curve25519.Signing.PrivateKey(rawRepresentation: Data(repeating: 7, count: 32))
        for row in try fixtures().filter({ $0["lookup"] != nil }) {
            var original = Data(base64Encoded: (row["prepared"] as! [String: Any])["transaction"] as! String)!
            original.replaceSubrange(1..<65, with: Data(repeating: 9, count: 64))
            let signed = try SolanaTransaction.partiallySign(transactionB64: original.base64EncodedString(), privateKey: privateKey)
            let output = Data(base64Encoded: signed)!, start = 1 + Int(original[0]) * 64
            XCTAssertEqual(output.subdata(in: 1..<65), original.subdata(in: 1..<65))
            XCTAssertEqual(output.subdata(in: start..<output.count), original.subdata(in: start..<original.count))
            XCTAssertTrue(privateKey.publicKey.isValidSignature(output.subdata(in: 65..<129), for: output.subdata(in: start..<output.count)))
        }
    }

    func testEveryBackendBuiltStage1ShapeIsAccepted() throws {
        let rows = try fixtures()
        XCTAssertEqual(rows.count, 30)
        for row in rows {
            let prepared = row["prepared"] as! [String: Any]
            XCTAssertNoThrow(try BalanceTransactionFirewall.validate(transactionB64: prepared["transaction"] as! String, intent: intent(row), lookupTables: tables(row)), row["name"] as! String)
        }
    }

    func testConfiguredTestPoolTransactionsRequireIndependentIdentity() throws {
        let url = try XCTUnwrap(Bundle(for: Self.self).url(forResource: "stage1-testpool-transactions", withExtension: "json"))
        let rows = try XCTUnwrap(JSONSerialization.jsonObject(with: Data(contentsOf: url)) as? [[String: Any]])
        XCTAssertEqual(rows.count, 30)
        for row in rows {
            let identity = row["testPool"] as! [String: String]
            let pool = Stage1TestPool(provider: identity["provider"]!, mint: identity["mint"]!)
            let wire = (row["prepared"] as! [String: Any])["transaction"] as! String
            let intent = intent(row)
            XCTAssertNoThrow(try BalanceTransactionFirewall.validate(transactionB64: wire, intent: intent,
                lookupTables: tables(row), stage1TestPool: pool), row["name"] as! String)
            let action = row["action"] as! String
            let description = row["intent"] as! [String: Any]
            if ["pledge", "convert-pledge", "begin-withdrawal", "complete-withdrawal"].contains(action) || description["claimType"] as? String == "cash" {
                XCTAssertThrowsError(try BalanceTransactionFirewall.validate(transactionB64: wire, intent: intent, lookupTables: tables(row)))
                XCTAssertThrowsError(try BalanceTransactionFirewall.validate(transactionB64: wire, intent: intent, lookupTables: tables(row),
                    stage1TestPool: .init(provider: pool.provider, mint: "11111111111111111111111111111111")))
            }
        }
    }

    func testEveryAccountIncludingProgramPayerRecipientAndCustodyIsPinned() throws {
        for row in try fixtures().filter({ $0["lookup"] == nil }) {
            let wire = (row["prepared"] as! [String: Any])["transaction"] as! String
            let message = try SolanaTransaction.parseLegacyMessage(transactionB64: wire)
            for index in message.accountKeys.indices {
                var mutant = Data(base64Encoded: wire)!
                // All vectors have a one-byte shortvec key count. Locate keys
                // in the message, not the deliberately empty signature slots.
                let keyStart = 1 + Int(mutant[0]) * 64 + 4
                mutant[keyStart + index * 32] ^= 1
                XCTAssertThrowsError(try BalanceTransactionFirewall.validate(transactionB64: mutant.base64EncodedString(), intent: intent(row), lookupTables: tables(row)), row["name"] as! String)
            }
            XCTAssertThrowsError(try BalanceTransactionFirewall.validate(transactionB64: wire,
                intent: intent(row, wallet: "11111111111111111111111111111112")))
        }
    }

    func testInstructionAmountLockProofAndRoleChangesFailClosed() throws {
        for row in try fixtures().filter({ $0["lookup"] == nil }) {
            let wire = (row["prepared"] as! [String: Any])["transaction"] as! String
            let message = try SolanaTransaction.parseLegacyMessage(transactionB64: wire)
            for instruction in message.instructions {
                let data = instruction.data
                let original = Data(base64Encoded: wire)!
                // Long data are unambiguous in these unsigned deterministic vectors.
                if data.count < 8 { continue }
                let range = try XCTUnwrap(original.range(of: data))
                for offset in Set([0, 7, min(8, data.count - 1), data.count - 1]) {
                    var mutant = original; mutant[range.lowerBound + offset] ^= 1
                    XCTAssertThrowsError(try BalanceTransactionFirewall.validate(transactionB64: mutant.base64EncodedString(), intent: intent(row)))
                }
            }
            var roles = Data(base64Encoded: wire)!
            let header = 1 + Int(roles[0]) * 64
            roles[header + 1] ^= 1
            XCTAssertThrowsError(try BalanceTransactionFirewall.validate(transactionB64: roles.base64EncodedString(), intent: intent(row)))
        }
    }
}
