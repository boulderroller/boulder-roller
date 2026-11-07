import XCTest
@testable import BoulderRoller

final class BalanceTransactionFirewallTests: XCTestCase {
    private let stakeIntent = BalanceTransactionIntent.stake(
        vaultId: 42,
        amountBaseUnits: Fixtures.stakeAmount,
        wallet: Fixtures.wallet
    )
    private let unstakeIntent = BalanceTransactionIntent.unstake(
        vaultId: 42,
        amountBaseUnits: Fixtures.unstakeAmount,
        wallet: Fixtures.wallet
    )

    func testBackendGeneratedStakeShapesAreAccepted() {
        let fixtures = [
            ("base", Fixtures.stakeBase),
            ("escrow only", Fixtures.stakeEscrowOnly),
            ("all initializers", Fixtures.stakeAllInitializers),
        ]
        for (name, fixture) in fixtures {
            XCTAssertNoThrow(
                try BalanceTransactionFirewall.validate(
                    transactionB64: fixture,
                    intent: stakeIntent
                ),
                name
            )
        }
    }

    func testBackendGeneratedUnstakeShapesAreAccepted() {
        let fixtures = [
            ("base", Fixtures.unstakeBase),
            ("collect", Fixtures.unstakeCollect),
            ("all optional instructions", Fixtures.unstakeAllOptionalInstructions),
        ]
        for (name, fixture) in fixtures {
            XCTAssertNoThrow(
                try BalanceTransactionFirewall.validate(
                    transactionB64: fixture,
                    intent: unstakeIntent
                ),
                name
            )
        }
    }

    func testVersionedPreparedMessageIsRejected() throws {
        XCTAssertThrowsError(
            try BalanceTransactionFirewall.validate(
                transactionB64: versioned(Fixtures.stakeBase),
                intent: stakeIntent
            )
        )
    }

    func testWrongProgramIsRejected() throws {
        let transaction = try replacingPublicKey(
            in: Fixtures.stakeBase,
            BalanceTransactionFirewall.boulderProgram,
            with: Fixtures.otherPublicKey
        )
        XCTAssertThrowsError(
            try BalanceTransactionFirewall.validate(
                transactionB64: transaction,
                intent: stakeIntent
            )
        )
    }

    func testWrongDiscriminatorIsRejected() throws {
        let expected = Data([0x93, 0x96, 0x5b, 0x0c, 0x13, 0xfa, 0xbd, 0x6a])
        let wrong = Data([0x92, 0x96, 0x5b, 0x0c, 0x13, 0xfa, 0xbd, 0x6a])
        let transaction = try replacingBytes(
            in: Fixtures.stakeBase,
            expected,
            with: wrong
        )
        XCTAssertThrowsError(
            try BalanceTransactionFirewall.validate(
                transactionB64: transaction,
                intent: stakeIntent
            )
        )
    }

    func testCoherentWrongVaultIsRejected() {
        XCTAssertThrowsError(
            try BalanceTransactionFirewall.validate(
                transactionB64: Fixtures.stakeForVault43,
                intent: stakeIntent
            )
        )
    }

    func testNoncanonicalAlternateBumpPDAIsRejected() throws {
        let transaction = try replacingPublicKey(
            in: Fixtures.stakeBase,
            Fixtures.vault42,
            with: Fixtures.vault42AlternateBump
        )
        XCTAssertThrowsError(
            try BalanceTransactionFirewall.validate(
                transactionB64: transaction,
                intent: stakeIntent
            )
        )
    }

    func testEd25519CurvePredicateMatchesSoldersParityVectors() throws {
        let vectors: [(String, Bool)] = [
            ("f235072d16e800bede31bbf8995f559019b4b29094b99c3587f545a9f84d0da6", false),
            ("f58214348e7a0773b70646dac8f90a635ac74b24cd68c2a19e48abc1af91cef1", false),
            ("0d72b73a9a96a58f722b7d85b5ec7015208d6a4c78eeb08e3489d0ff36acceda", false),
            ("b4bfdd0d3eb677e0acba8970fdc621de12a7c2bcccf3c4544af9926842da18ba", true),
            ("009c1cd3c5da998de6bff08fa30f85bcec0100248874dc7dc93250ac214822b1", false),
            ("1e7ba9d42d06af2414a0408af44836203004c2eb0292325865d36615652d8f6f", true),
            ("dc0478ebf04fdb8b69cb9b78eb976c89043e098434ee9721e271462ccb370046", false),
            ("6a1cd81b51fe7042588d42f6bc4f0ca60aac4e94d1f6e04824582ed2b9c262da", false),
            ("540a466e79003f50a1031df6dc0c5bdf620894c8b807e79b9ffa6866ef322128", true),
            ("f1ebe0d0cc457b76454b54a7dfe58da74de0431e6fedada9558c4391552dd262", false),
            ("f254ab4406fff2b8423c5c18def94eae1d7ad93843d78e19112eb831f68c5449", true),
            ("c522e4c7860ac2bc3477e426342a1fe03644b3f0efda380172a0c2f14b1cd3cf", true),
            ("11634d1fe445723912913d7c754207253526ca6878b14a3e0e8c024e0bfb4a42", true),
            ("36a725f881c8cf4ffce5b44fef05dd16bf5100899e30094bf6258326dd2ca1fb", true),
            ("42b3282cedfc3b58a9812a6614c43a274dd5a1a58f102b7ecc32fe1d9da06830", false),
            ("fbb5b2953b04fee666281aaf42cd17a448b68f3d3ce0ce026c0208354a36fb84", true),
            ("0289ff8221f1bdb84564028f3c717273fcc37bb8b4c47ceac8946071b29fa273", true),
            ("5bc2ced9f16d08f8f60aa74b9ccbc118c661e2c8ff0e022610a01112ac4c8233", false),
            ("fd5ba1185c04b76f26740325eb73be1ce7bcee8c939ce87d8bd81674e0953a95", false),
            ("c29686646274f36dc567263977e73739c121b44298cbafdc1411b1d23510bdbe", true),
            ("a4dbd9b1913e084edb5bc9c43ad60cf609d7292b219e5468162e5c49b65cf11d", false),
            ("20f043cebf584ab3d514e6b7aabf161297fb48e874eec959b04f8d1ffc851b8f", false),
            ("8474d3e183fd60f525430722a7cb8cd992b7c33fc8905016d7174b9ce3d3d579", false),
            ("972c7e82c4911c0e8fdc6f4fc43570955b29637afb4cc0a33d226413b405d2fb", false),
        ]

        for (hex, expected) in vectors {
            XCTAssertEqual(
                SolanaProgramAddress.isEd25519CurvePoint(try data(hex: hex)),
                expected,
                hex
            )
        }
    }

    func testWrongMintIsRejected() throws {
        let transaction = try replacingPublicKey(
            in: Fixtures.stakeEscrowOnly,
            BalanceTransactionFirewall.calMint,
            with: BalanceTransactionFirewall.dungMint
        )
        XCTAssertThrowsError(
            try BalanceTransactionFirewall.validate(
                transactionB64: transaction,
                intent: stakeIntent
            )
        )
    }

    func testWrongAmountIsRejected() {
        XCTAssertThrowsError(
            try BalanceTransactionFirewall.validate(
                transactionB64: Fixtures.stakeBase,
                intent: .stake(
                    vaultId: 42,
                    amountBaseUnits: Fixtures.stakeAmount + 1,
                    wallet: Fixtures.wallet
                )
            )
        )
    }

    func testWrongFeePayerIsRejected() throws {
        let transaction = try replacingPublicKey(
            in: Fixtures.stakeBase,
            BalanceTransactionFirewall.feePayer,
            with: Fixtures.otherPublicKey
        )
        XCTAssertThrowsError(
            try BalanceTransactionFirewall.validate(
                transactionB64: transaction,
                intent: stakeIntent
            )
        )
    }

    func testWrongRiderIsRejected() {
        XCTAssertThrowsError(
            try BalanceTransactionFirewall.validate(
                transactionB64: Fixtures.stakeBase,
                intent: .stake(
                    vaultId: 42,
                    amountBaseUnits: Fixtures.stakeAmount,
                    wallet: Fixtures.otherPublicKey
                )
            )
        )
    }

    func testRiderNotRequiredToSignIsRejected() throws {
        XCTAssertThrowsError(
            try BalanceTransactionFirewall.validate(
                transactionB64: removingRiderSignatureRequirement(Fixtures.stakeBase),
                intent: stakeIntent
            )
        )
    }

    func testWrongTreasuryAccountIsRejected() throws {
        let transaction = try replacingPublicKey(
            in: Fixtures.unstakeCollect,
            BalanceTransactionFirewall.protocolTreasury,
            with: Fixtures.otherPublicKey
        )
        XCTAssertThrowsError(
            try BalanceTransactionFirewall.validate(
                transactionB64: transaction,
                intent: unstakeIntent
            )
        )
    }

    func testExtraInstructionIsRejected() {
        XCTAssertThrowsError(
            try BalanceTransactionFirewall.validate(
                transactionB64: Fixtures.stakeWithExtraInstruction,
                intent: stakeIntent
            )
        )
    }

    func testFirewallRejectsBeforeTransactionSignerResolvesAWallet() async throws {
        let transaction = try replacingPublicKey(
            in: Fixtures.stakeBase,
            BalanceTransactionFirewall.boulderProgram,
            with: Fixtures.otherPublicKey
        )
        do {
            _ = try await TransactionSigner.sign(
                transactionB64: transaction,
                wallet: Fixtures.wallet,
                intent: stakeIntent
            )
            XCTFail("Expected the firewall to reject before wallet resolution")
        } catch is BalanceTransactionFirewall.ValidationError {
            // The policy error, rather than SignerError.noWallet, proves order.
        } catch {
            XCTFail("Unexpected error: \(error)")
        }
    }

    func testPinnedPublicKeysDecodeToTheCanonicalBase58Bytes() throws {
        let addresses = [
            BalanceTransactionFirewall.boulderProgram,
            BalanceTransactionFirewall.tokenProgram,
            BalanceTransactionFirewall.associatedTokenProgram,
            BalanceTransactionFirewall.systemProgram,
            BalanceTransactionFirewall.rentSysvar,
            BalanceTransactionFirewall.feePayer,
            BalanceTransactionFirewall.backendAuthority,
            BalanceTransactionFirewall.calMint,
            BalanceTransactionFirewall.dungMint,
            BalanceTransactionFirewall.protocolTreasury,
            BalanceTransactionFirewall.stage1CashMint,
            Fixtures.wallet,
        ]
        for address in addresses {
            let decoded = try BalanceTransactionFirewall.decodePublicKey(address)
            XCTAssertEqual(decoded.count, 32)
            XCTAssertEqual(Base58.encode(decoded), address)
        }
    }

    private func replacingPublicKey(
        in transaction: String,
        _ old: String,
        with new: String
    ) throws -> String {
        try replacingBytes(
            in: transaction,
            BalanceTransactionFirewall.decodePublicKey(old),
            with: BalanceTransactionFirewall.decodePublicKey(new)
        )
    }

    private func replacingBytes(
        in transaction: String,
        _ old: Data,
        with new: Data
    ) throws -> String {
        guard old.count == new.count,
              var wire = Data(base64Encoded: transaction),
              let range = wire.range(of: old),
              wire.range(of: old, in: range.upperBound..<wire.endIndex) == nil
        else {
            throw FixtureError.invalidMutation
        }
        wire.replaceSubrange(range, with: new)
        return wire.base64EncodedString()
    }

    private func data(hex: String) throws -> Data {
        guard hex.count.isMultiple(of: 2) else { throw FixtureError.invalidMutation }
        var output = Data()
        var index = hex.startIndex
        while index < hex.endIndex {
            let end = hex.index(index, offsetBy: 2)
            guard let byte = UInt8(hex[index..<end], radix: 16) else {
                throw FixtureError.invalidMutation
            }
            output.append(byte)
            index = end
        }
        return output
    }

    private func versioned(_ transaction: String) throws -> String {
        guard var wire = Data(base64Encoded: transaction), !wire.isEmpty else {
            throw FixtureError.invalidMutation
        }
        let signatureCount = Int(wire[wire.startIndex])
        let messageStart = 1 + signatureCount * 64
        guard wire.indices.contains(messageStart) else { throw FixtureError.invalidMutation }
        wire[messageStart] |= 0x80
        return wire.base64EncodedString()
    }

    private func removingRiderSignatureRequirement(_ transaction: String) throws -> String {
        guard var wire = Data(base64Encoded: transaction), wire.first == 3 else {
            throw FixtureError.invalidMutation
        }
        // These backend-generated stake fixtures use a one-byte shortvec and
        // signer order fee payer, backend authority, rider.
        wire.removeSubrange((1 + 2 * 64)..<(1 + 3 * 64))
        wire[wire.startIndex] = 2
        let messageStart = 1 + 2 * 64
        guard wire.indices.contains(messageStart) else { throw FixtureError.invalidMutation }
        wire[messageStart] = 2
        return wire.base64EncodedString()
    }

    private enum FixtureError: Error {
        case invalidMutation
    }
}

/// Real legacy messages produced by backend `solana_direct` instruction
/// builders and solders message compilation with a zero blockhash/signatures.
/// They exercise the independent Swift parser/policy rather than a Swift test
/// builder that could repeat the implementation's mistakes.
private enum Fixtures {
    static let wallet = "G8DM5Dn12fsgkKxbdUUtFVJsqMXTcJqPU9no7koqwcKH"
    static let otherPublicKey = "DpLPBaRuLnBsR3P3meU1tmiNUxreXwskXBebTYKvNGne"
    static let vault42 = "FxzRhZmhRXMhKkhVcqDeo5n15L36aAhzzQ1tL3DCKjA9"
    static let vault42AlternateBump = "4kJXMHRsTf5Bh1Gswm8r5rRNSUrEjki7VC2rQ17EBJGH"
    static let stakeAmount: UInt64 = 123_000_000_000
    static let unstakeAmount: UInt64 = 456_789

    static let stakeBase = "AwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAMABQ6BIungXYT5DauEINzUbsybVINZwXFqXmSAcAjG//6iNKgMBil9EdQKvslcgFznwaKtdVfGsITNf0AuETaeUIN94LhUTjWGKVDu6TzZ+iyLIPskKSyOquUfIApk8XnA7gAYyVAxsHAWRgYhj98XVe4s43ytjjfO9YD7vbdbSwxh0DypZMPJoUebIey2/sJ0X+UMBg3QAmMpqtnxMD+2ZcfHgcl39dztAKEY1xEfeKHCvqxYFkLHSdvtDr1iKlZP0oyNp9aRymQRlbMG+1aeKxrbkFmqteb+sW+z9ER9TSaFxd5bfjraudsO3pDEWJCWe6CnZ/JK0mTqECjF73YmW676+wmxesxo4+ZaEwTCRzxnEoanHgHAfAEUgl9PVyTVp1gAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAbd9uHXZaGT2cvhRs7reawctIXtX1s3kTqM9YV+/wCpPaJ8thb9C3OIDtYOGU5mXOMAlK0YCCOEWzEq4XsD+Ba8hr3qBx95/T3w3JCboSuiXdMjXV7sYV9hH/k9cYLGrMiEHJRKYAmR37tH2QeeNqayuH4YRt2PatjvnVV/A72WAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACDQgHAgYEAwEKCQgUwMy35L7O9A0MBwYMCwECCAUEAwoJEJOWWwwT+r1qAA5foxwAAAA="

    static let stakeEscrowOnly = "AwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAMABxCBIungXYT5DauEINzUbsybVINZwXFqXmSAcAjG//6iNKgMBil9EdQKvslcgFznwaKtdVfGsITNf0AuETaeUIN94LhUTjWGKVDu6TzZ+iyLIPskKSyOquUfIApk8XnA7gAYyVAxsHAWRgYhj98XVe4s43ytjjfO9YD7vbdbSwxh0DypZMPJoUebIey2/sJ0X+UMBg3QAmMpqtnxMD+2ZcfHgcl39dztAKEY1xEfeKHCvqxYFkLHSdvtDr1iKlZP0oyNp9aRymQRlbMG+1aeKxrbkFmqteb+sW+z9ER9TSaFxd5bfjraudsO3pDEWJCWe6CnZ/JK0mTqECjF73YmW676+wmxesxo4+ZaEwTCRzxnEoanHgHAfAEUgl9PVyTVp1gAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAan1RcZLFxRIYzJTD1K8X9Y2u4Im6H9ROPb2YoAAAAABt324ddloZPZy+FGzut5rBy0he1fWzeROoz1hX7/AKk1h4IDyxsu+V8SavOXdMQUdfrwpx6LU+3G21/hnDODfj2ifLYW/QtziA7WDhlOZlzjAJStGAgjhFsxKuF7A/gWvIa96gcfef098NyQm6Erol3TI11e7GFfYR/5PXGCxqzIhByUSmAJkd+7R9kHnjamsrh+GEbdj2rY751VfwO9lgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAw8IBw0FDAALCQoITbLQl9giG9APCAcCBgQDAQsJCBTAzLfkvs70DwwHBg4NAQIIBQQDCwkQk5ZbDBP6vWoADl+jHAAAAA=="

    static let stakeAllInitializers = "AwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAMABxCBIungXYT5DauEINzUbsybVINZwXFqXmSAcAjG//6iNKgMBil9EdQKvslcgFznwaKtdVfGsITNf0AuETaeUIN94LhUTjWGKVDu6TzZ+iyLIPskKSyOquUfIApk8XnA7gAYyVAxsHAWRgYhj98XVe4s43ytjjfO9YD7vbdbSwxh0DypZMPJoUebIey2/sJ0X+UMBg3QAmMpqtnxMD+2ZcfHgcl39dztAKEY1xEfeKHCvqxYFkLHSdvtDr1iKlZP0oyNp9aRymQRlbMG+1aeKxrbkFmqteb+sW+z9ER9TSaFxd5bfjraudsO3pDEWJCWe6CnZ/JK0mTqECjF73YmW676+wmxesxo4+ZaEwTCRzxnEoanHgHAfAEUgl9PVyTVp1gAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAan1RcZLFxRIYzJTD1K8X9Y2u4Im6H9ROPb2YoAAAAABt324ddloZPZy+FGzut5rBy0he1fWzeROoz1hX7/AKk1h4IDyxsu+V8SavOXdMQUdfrwpx6LU+3G21/hnDODfj2ifLYW/QtziA7WDhlOZlzjAJStGAgjhFsxKuF7A/gWvIa96gcfef098NyQm6Erol3TI11e7GFfYR/5PXGCxqzIhByUSmAJkd+7R9kHnjamsrh+GEbdj2rY751VfwO9lgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABA8GBwQACwkKCGHCiO72/0eBDwgHDQUMAAsJCghNstCX2CIb0A8IBwIGBAMBCwkIFMDMt+S+zvQPDAcGDg0BAggFBAMLCRCTllsME/q9agAOX6McAAAA"

    static let unstakeBase = "AgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAgAEDYEi6eBdhPkNq4Qg3NRuzJtUg1nBcWpeZIBwCMb//qI04LhUTjWGKVDu6TzZ+iyLIPskKSyOquUfIApk8XnA7gAYyVAxsHAWRgYhj98XVe4s43ytjjfO9YD7vbdbSwxh0DWHggPLGy75XxJq85d0xBR1+vCnHotT7cbbX+GcM4N+PKlkw8mhR5sh7Lb+wnRf5QwGDdACYymq2fEwP7Zlx8eByXf13O0AoRjXER94ocK+rFgWQsdJ2+0OvWIqVk/SjI2n1pHKZBGVswb7Vp4rGtuQWaq15v6xb7P0RH1NJoXF3lt+Otq52w7ekMRYkJZ7oKdn8krSZOoQKMXvdiZbrvr7CbF6zGjj5loTBMJHPGcShqceAcB8ARSCX09XJNWnWAbd9uHXZaGT2cvhRs7reawctIXtX1s3kTqM9YV+/wCpPaJ8thb9C3OIDtYOGU5mXOMAlK0YCCOEWzEq4XsD+Ba8hr3qBx95/T3w3JCboSuiXdMjXV7sYV9hH/k9cYLGrMiEHJRKYAmR37tH2QeeNqayuH4YRt2PatjvnVV/A72WAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABDAsHBgsKAQgFAwQCCRCPSJJspjYsEFX4BgAAAAAA"

    static let unstakeCollect = "AgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAgAFEYEi6eBdhPkNq4Qg3NRuzJtUg1nBcWpeZIBwCMb//qI04LhUTjWGKVDu6TzZ+iyLIPskKSyOquUfIApk8XnA7gAYyVAxsHAWRgYhj98XVe4s43ytjjfO9YD7vbdbSwxh0DWHggPLGy75XxJq85d0xBR1+vCnHotT7cbbX+GcM4N+PKlkw8mhR5sh7Lb+wnRf5QwGDdACYymq2fEwP7Zlx8eByXf13O0AoRjXER94ocK+rFgWQsdJ2+0OvWIqVk/SjITjxFFs/kX7tAH7rwRyo5MueNgUL6PieIHGITbWXFwliYAuPAFtdBAQH5PvHCCTjKZiiMdYsBaOXhV/dm2PnPyNp9aRymQRlbMG+1aeKxrbkFmqteb+sW+z9ER9TSaFxa/KSEOVhSSjOz8OOHSDnKkGek3OkRqR2ucM0iTjdFTV3lt+Otq52w7ekMRYkJZ7oKdn8krSZOoQKMXvdiZbrvr7CbF6zGjj5loTBMJHPGcShqceAcB8ARSCX09XJNWnWAbd9uHXZaGT2cvhRs7reawctIXtX1s3kTqM9YV+/wCpPaJ8thb9C3OIDtYOGU5mXOMAlK0YCCOEWzEq4XsD+BaEyA++B9rCD/erLoek+MBjaS0pVyT4HBJbl9pj5unRnryGveoHH3n9PfDckJuhK6Jd0yNdXuxhX2Ef+T1xgsasyIQclEpgCZHfu0fZB542prK4fhhG3Y9q2O+dVX8DvZYAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAIQDAoIDwEACQYGBw0ODAjcdrf10e1CPRALCggPDQELBQMEAgwQj0iSbKY2LBBV+AYAAAAAAA=="

    static let unstakeAllOptionalInstructions = "AgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAgAIFIEi6eBdhPkNq4Qg3NRuzJtUg1nBcWpeZIBwCMb//qI04LhUTjWGKVDu6TzZ+iyLIPskKSyOquUfIApk8XnA7gAYyVAxsHAWRgYhj98XVe4s43ytjjfO9YD7vbdbSwxh0DWHggPLGy75XxJq85d0xBR1+vCnHotT7cbbX+GcM4N+PKlkw8mhR5sh7Lb+wnRf5QwGDdACYymq2fEwP7Zlx8eByXf13O0AoRjXER94ocK+rFgWQsdJ2+0OvWIqVk/SjITjxFFs/kX7tAH7rwRyo5MueNgUL6PieIHGITbWXFwliYAuPAFtdBAQH5PvHCCTjKZiiMdYsBaOXhV/dm2PnPyNp9aRymQRlbMG+1aeKxrbkFmqteb+sW+z9ER9TSaFxa/KSEOVhSSjOz8OOHSDnKkGek3OkRqR2ucM0iTjdFTV3lt+Otq52w7ekMRYkJZ7oKdn8krSZOoQKMXvdiZbrvr7CbF6zGjj5loTBMJHPGcShqceAcB8ARSCX09XJNWnWAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAABqfVFxksXFEhjMlMPUrxf1ja7gibof1E49vZigAAAAAG3fbh12Whk9nL4UbO63msHLSF7V9bN5E6jPWFfv8AqT2ifLYW/QtziA7WDhlOZlzjAJStGAgjhFsxKuF7A/gWhMgPvgfawg/3qy6HpPjAY2ktKVck+BwSW5faY+bp0Z6MlyWPTiSJ8bs9ECkUjg2DC1oTmdr/EIQEjnvY2+n4WbyGveoHH3n9PfDckJuhK6Jd0yNdXuxhX2Ef+T1xgsasyIQclEpgCZHfu0fZB542prK4fhhG3Y9q2O+dVX8DvZYAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAQRBwAGAQkMDg0AEwwKCBIBAAkGBgcPEA4I3Ha39dHtQj0RBwALAQMMDg0AEwsKCBIPAQsFAwQCDhCPSJJspjYsEFX4BgAAAAAA"

    static let stakeForVault43 = "AwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAMABQ6BIungXYT5DauEINzUbsybVINZwXFqXmSAcAjG//6iNKgMBil9EdQKvslcgFznwaKtdVfGsITNf0AuETaeUIN94LhUTjWGKVDu6TzZ+iyLIPskKSyOquUfIApk8XnA7gAkUAFi0cS490NkauLqxPwHsbac459sYt2J0XzYlwKxR03Yu2qFn5kOJ5QHFLRjXEUgz0MQSUdw6Nx2i2nNVvNsjjWvWOncqYYjagvcyJ/LB51YK6UJ4fbJel/CKMRHkQapuDhSBhMvtpuw3nSmMbzQ0BsW7y29emy+Jyi0eCSt4uF3AVHdxRsuXdS8l0Z+ZWiXwAGkCcCG3LvThufRUjsi+wmxesxo4+ZaEwTCRzxnEoanHgHAfAEUgl9PVyTVp1gAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAbd9uHXZaGT2cvhRs7reawctIXtX1s3kTqM9YV+/wCpPaJ8thb9C3OIDtYOGU5mXOMAlK0YCCOEWzEq4XsD+Bao7tdlO9VtmbnZJ+RLTrOXuHslkNro7Q05fj7KkTcsq8iEHJRKYAmR37tH2QeeNqayuH4YRt2PatjvnVV/A72WAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACDQgHAgYDBQEKCQgUwMy35L7O9A0MBwYMCwECCAQDBQoJEJOWWwwT+r1qAA5foxwAAAA="

    static let stakeWithExtraInstruction = "AwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAMABQ6BIungXYT5DauEINzUbsybVINZwXFqXmSAcAjG//6iNKgMBil9EdQKvslcgFznwaKtdVfGsITNf0AuETaeUIN94LhUTjWGKVDu6TzZ+iyLIPskKSyOquUfIApk8XnA7gAYyVAxsHAWRgYhj98XVe4s43ytjjfO9YD7vbdbSwxh0DypZMPJoUebIey2/sJ0X+UMBg3QAmMpqtnxMD+2ZcfHgcl39dztAKEY1xEfeKHCvqxYFkLHSdvtDr1iKlZP0oyNp9aRymQRlbMG+1aeKxrbkFmqteb+sW+z9ER9TSaFxd5bfjraudsO3pDEWJCWe6CnZ/JK0mTqECjF73YmW676+wmxesxo4+ZaEwTCRzxnEoanHgHAfAEUgl9PVyTVp1gAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAbd9uHXZaGT2cvhRs7reawctIXtX1s3kTqM9YV+/wCpPaJ8thb9C3OIDtYOGU5mXOMAlK0YCCOEWzEq4XsD+Ba8hr3qBx95/T3w3JCboSuiXdMjXV7sYV9hH/k9cYLGrMiEHJRKYAmR37tH2QeeNqayuH4YRt2PatjvnVV/A72WAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAADDQgHAgYEAwEKCQgUwMy35L7O9A0MBwYMCwECCAUEAwoJEJOWWwwT+r1qAA5foxwAAAANDAcGDAsBAggFBAMKCRCTllsME/q9agAOX6McAAAA"
}
