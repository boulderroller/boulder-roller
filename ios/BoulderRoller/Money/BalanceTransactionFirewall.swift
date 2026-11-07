import Foundation

enum BalanceTransactionIntent {
    case stake(vaultId: Int, amountBaseUnits: UInt64, wallet: String)
    case unstake(vaultId: Int, amountBaseUnits: UInt64, wallet: String)
    case stage1(Stage1TransactionIntent, wallet: String)

    fileprivate var values: (vaultId: Int, amount: UInt64, wallet: String, operation: Operation)? {
        switch self {
        case let .stake(vaultId, amount, wallet):
            return (vaultId, amount, wallet, .stake)
        case let .unstake(vaultId, amount, wallet):
            return (vaultId, amount, wallet, .unstake)
        case .stage1:
            return nil
        }
    }

    fileprivate enum Operation {
        case stake
        case unstake
    }
}

struct Stage1ClaimProof: Codable {
    let hash: Data
    let sum: UInt128
}

struct Stage1ClaimLeaf: Codable {
    let hill: String
    let week: UInt64
    let index: UInt32
    let amount: UInt64
    let proof: [Stage1ClaimProof]
}

struct Stage1CashLeaf: Codable {
    let leaf: Stage1ClaimLeaf
    let cap: UInt64
    let frozenAt: Int64
    let auditHash: Data
}

struct Stage1DungLeaf: Codable {
    let leaf: Stage1ClaimLeaf
    let role: UInt8
}

enum Stage1LookupMode: String, Codable { case create, deactivate, close }

// Screens construct pledge, notice and convert intents from the person's own
// inputs and independently loaded context, never the prepare response's echoed
// intent. Otherwise a compromised backend could choose the checked amount,
// lock or hill. TransactionSigner must receive that independent intent.
enum Stage1TransactionIntent: Codable {
    case registration
    case cancelPledge(hill: String, mint: String, depositID: UInt64)
    case pledge(hill: String, climb: String, mint: String, depositID: UInt64, amount: UInt64,
                lockWeeks: UInt16, bonded: Bool, backingMints: [String])
    case withdrawalNotice(hill: String, depositID: UInt64, requestID: UInt64, basisLamports: UInt64)
    case cancelNotice(depositID: UInt64, requestID: UInt64)
    case beginWithdrawal(hill: String, mint: String, depositID: UInt64, requestID: UInt64, week: UInt64, refreshRate: Bool = true)
    case completeWithdrawal(hill: String, mint: String, depositID: UInt64, requestID: UInt64, week: UInt64, refreshRate: Bool = true)
    case convertPledge(hill: String, mint: String, depositID: UInt64, lockWeeks: UInt16, refreshRate: Bool = true)
    case cashClaim(mint: String, leaves: [Stage1CashLeaf], single: Bool = false)
    case dungClaim(leaves: [Stage1DungLeaf], single: Bool = false)
    case claimTransport(mode: Stage1LookupMode, table: String, recentSlot: UInt64 = 0, addresses: [String] = [])
}

// ABI c0811f476ca9deaf5942e574588bbd68181d701cdc5bfc1719e6fc27a18cd441.
// Mirrors the portal policy; endpoint responses cannot change these identities.
private let stage1Providers = [
    "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn": "Jito4APyf642JPZPx3hGc6WWJ8zPKtRbRs4P815Awbb",
    "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So": "8szGkuLTAux9XMgZ2vtY39jVSowEcpBfFfD8hXSEqdGC",
    "jupSoLaHXQiZZTSfEWMTRRgpnyFm8f6sZdosWBjx93v": "8VpRhuxa7sUUepdY3kQiTmX9rS5vx4WgaXiAnXq4KCtr",
]

extension BalanceTransactionFirewall {
    private struct Stage1Meta {
        let key: Data
        var signer = false
        var writable = false
    }

    private struct Stage1Instruction {
        let program: Data
        let data: Data
        let keys: [Stage1Meta]
    }

    private static func stage1LE<T: FixedWidthInteger>(_ value: T) -> Data {
        var encoded = value.littleEndian
        return Data(bytes: &encoded, count: MemoryLayout<T>.size)
    }

    private static func stage1Hex(_ value: String) throws -> Data {
        guard value.count.isMultiple(of: 2) else { throw ValidationError.rejected }
        let chars = Array(value)
        return try Data(stride(from: 0, to: chars.count, by: 2).map {
            guard let byte = UInt8(String(chars[$0...($0 + 1)]), radix: 16) else { throw ValidationError.rejected }
            return byte
        })
    }

    private static func validateStage1(_ message: SolanaTransaction.LegacyMessage,
                                       intent: Stage1TransactionIntent, wallet walletString: String,
                                       testPool: Stage1TestPool?) throws {
        let wallet = try decodePublicKey(walletString), program = try decodePublicKey(boulderProgram)
        let fee = try decodePublicKey(feePayer), token = try decodePublicKey(tokenProgram)
        let system = try decodePublicKey(systemProgram), associated = try decodePublicKey(associatedTokenProgram)
        let rent = try decodePublicKey(rentSysvar), dungMintKey = try decodePublicKey(dungMint)
        let usdc = try decodePublicKey("DpLPBaRuLnBsR3P3meU1tmiNUxreXwskXBebTYKvNGne"), stage1Cash = try decodePublicKey(stage1CashMint)
        let forbidden = try Set([boulderProgram, feePayer, backendAuthority, tokenProgram, associatedTokenProgram,
            systemProgram, rentSysvar, calMint, dungMint, protocolTreasury].map(decodePublicKey))
        guard message.feePayer == fee, !forbidden.contains(wallet) else { throw ValidationError.rejected }
        func ro(_ key: Data) -> Stage1Meta { Stage1Meta(key: key) }
        func rw(_ key: Data) -> Stage1Meta { Stage1Meta(key: key, writable: true) }
        func sign(_ key: Data, _ writable: Bool = false) -> Stage1Meta { Stage1Meta(key: key, signer: true, writable: writable) }
        func pda(_ seed: String, _ parts: Data...) throws -> Data {
            guard let key = SolanaProgramAddress.canonicalAddress(seeds: [Data(seed.utf8)] + parts, program: program) else {
                throw ValidationError.rejected
            }
            return key
        }
        func ata(_ mint: Data) throws -> Data {
            guard let key = SolanaProgramAddress.canonicalAddress(seeds: [wallet, token, mint], program: associated) else {
                throw ValidationError.rejected
            }
            return key
        }
        func provider(_ mint: String) throws -> [Stage1Meta] {
            guard let address = stage1Providers[mint] ?? (testPool?.mint == mint ? testPool?.provider : nil) else { throw ValidationError.rejected }
            return try [ro(decodePublicKey(address)), ro(decodePublicKey(mint))]
        }
        func lock(_ weeks: UInt16) throws -> Data {
            guard [0, 13, 26, 52].contains(weeks) else { throw ValidationError.rejected }
            return stage1LE(weeks)
        }
        let city = try pda("s1v1_city"), registration = try pda("s1v1_recipient", wallet)
        var expected: [Stage1Instruction] = []
        func add(_ discriminator: String, _ args: Data = Data(), _ keys: [Stage1Meta]) throws {
            expected.append(Stage1Instruction(program: program, data: try stage1Hex(discriminator) + args, keys: keys))
        }
        func add(_ discriminator: String, _ keys: [Stage1Meta]) throws {
            try add(discriminator, Data(), keys)
        }
        func createATA(_ mint: Data) throws {
            expected.append(Stage1Instruction(program: associated, data: Data([1]), keys:
                try [sign(wallet, true), rw(ata(mint)), ro(wallet), ro(mint), ro(system), ro(token)]))
        }
        func refreshRate(_ mintString: String) throws {
            let mint = try decodePublicKey(mintString)
            try add("e1281bbd5a27f453", [rw(city), rw(pda("s1v1_asset", mint))] + provider(mintString))
        }
        func funding(_ hill: Data, _ mint: Data, _ week: UInt64) throws -> Data {
            let asset = try pda("s1v1_asset", mint), cursor = try pda("s1v1_cursor", hill, mint)
            let book = try pda("s1v1_funding", hill, mint, stage1LE(week))
            try add("f44e381663dfd514", [ro(city), rw(hill), ro(asset), rw(cursor), sign(fee, true), ro(system)])
            try add("2efe77a2baab5945", stage1LE(week), [ro(city), rw(hill), ro(asset), rw(book), sign(fee, true), ro(system), ro(cursor)])
            return book
        }
        func lot(_ id: UInt64) throws -> Data { try pda("s1v1_lot", wallet, stage1LE(id)) }
        func request(_ lot: Data, _ id: UInt64) throws -> Data { try pda("s1v1_request", lot, stage1LE(id)) }
        func claimBytes(_ leaf: Stage1ClaimLeaf) throws -> Data {
            guard leaf.index <= 65535, leaf.amount > 0, leaf.proof.count <= 16 else { throw ValidationError.rejected }
            var result = stage1LE(leaf.index) + stage1LE(leaf.amount) + stage1LE(UInt32(leaf.proof.count))
            for node in leaf.proof {
                guard node.hash.count == 32 else { throw ValidationError.rejected }
                result += node.hash + stage1LE(node.sum)
            }
            return result
        }
        switch intent {
        case let .claimTransport(mode, tableString, slot, addresses):
            let lookup = try decodePublicKey("AddressLookupTab1e1111111111111111111111111"), table = try decodePublicKey(tableString)
            func lookupIX(_ data: Data, _ keys: [Stage1Meta]) {
                expected.append(Stage1Instruction(program: lookup, data: data, keys: keys))
            }
            if mode == .create {
                guard (1...11).contains(addresses.count), Set(addresses).count == addresses.count,
                      let derivation = SolanaProgramAddress.canonicalAddressAndBump(seeds: [wallet, stage1LE(slot)], program: lookup),
                      derivation.address == table else { throw ValidationError.rejected }
                lookupIX(stage1LE(UInt32(0)) + stage1LE(slot) + Data([derivation.bump]), [rw(table), sign(wallet), sign(wallet, true), ro(system)])
                var data = stage1LE(UInt32(2)) + stage1LE(UInt64(addresses.count))
                for address in addresses { data += try decodePublicKey(address) }
                lookupIX(data, [rw(table), sign(wallet), sign(wallet, true), ro(system)])
            } else {
                guard addresses.isEmpty, slot == 0 else { throw ValidationError.rejected }
                lookupIX(stage1LE(UInt32(mode == .deactivate ? 3 : 4)), [rw(table), sign(wallet)] + (mode == .close ? [rw(wallet)] : []))
            }
        case .registration:
            try add("a71e21623cbb3b94", wallet, [rw(registration), sign(wallet), sign(fee, true), ro(system)])
        case let .pledge(hillString, climbString, mintString, depositID, amount, weeks, bonded, backing):
            guard amount > 0 else { throw ValidationError.rejected }
            let hill = try decodePublicKey(hillString), mint = try decodePublicKey(mintString), parent = try lot(depositID)
            var remaining: [Stage1Meta] = []
            _ = try provider(mintString)
            if bonded {
                guard backing.isEmpty else { throw ValidationError.rejected }
                remaining = try provider(mintString)
            } else {
                guard backing.count <= (testPool == nil ? 3 : 4), Set(backing).count == backing.count, backing.contains(mintString) else { throw ValidationError.rejected }
                for item in backing { remaining += try [rw(pda("s1v1_asset", decodePublicKey(item)))] + provider(item) }
            }
            try add("eb2f9cfe0058d48e", stage1LE(depositID) + stage1LE(amount) + lock(weeks),
                [rw(city), rw(hill), ro(decodePublicKey(climbString)), rw(pda("s1v1_asset", mint)), ro(mint), rw(parent),
                 rw(pda("s1v1_custody", parent)), rw(pda("s1v1_owner", parent)), rw(ata(mint)), sign(wallet, true), ro(token), ro(system), ro(rent)] + remaining)
        case let .cancelPledge(hillString, mintString, depositID):
            let parent = try lot(depositID), mint = try decodePublicKey(mintString)
            try createATA(mint)
            try add("28693d7e979934d9", [rw(city), rw(decodePublicKey(hillString)), rw(parent), rw(pda("s1v1_asset", mint)),
                rw(pda("s1v1_custody", parent)), rw(pda("s1v1_owner", parent)), rw(ata(mint)), sign(wallet), ro(token)])
        case let .withdrawalNotice(hillString, depositID, requestID, basis):
            guard basis > 0 else { throw ValidationError.rejected }
            let parent = try lot(depositID)
            try add("fb5579cd38c90cb1", stage1LE(requestID) + stage1LE(basis),
                    [ro(city), rw(decodePublicKey(hillString)), rw(parent), rw(request(parent, requestID)), sign(wallet, true), ro(system)])
        case let .cancelNotice(depositID, requestID):
            let parent = try lot(depositID)
            try add("b768b5fa1c80d246", [rw(parent), rw(request(parent, requestID)), sign(wallet)])
        case let .convertPledge(hillString, mintString, depositID, weeks, refresh):
            if refresh { try refreshRate(mintString) }
            let parent = try lot(depositID), mint = try decodePublicKey(mintString)
            try add("a275daef01463ec0", lock(weeks), [ro(city), ro(decodePublicKey(hillString)), rw(parent), ro(pda("s1v1_asset", mint)),
                rw(pda("s1v1_custody", parent)), rw(pda("s1v1_owner", parent)), sign(wallet), ro(token)] + provider(mintString))
        case let .beginWithdrawal(hillString, mintString, depositID, requestID, week, refresh):
            if refresh { try refreshRate(mintString) }
            let parent = try lot(depositID), req = try request(parent, requestID), exit = try pda("s1v1_exit", req)
            let hill = try decodePublicKey(hillString), mint = try decodePublicKey(mintString), book = try funding(hill, mint, week)
            try add("6c74f43791619c74", [rw(city), rw(hill), rw(parent), rw(req), ro(mint), rw(pda("s1v1_asset", mint)),
                rw(pda("s1v1_custody", parent)), rw(pda("s1v1_owner", parent)), rw(pda("s1v1_earnings", mint)),
                rw(exit), rw(pda("s1v1_custody", exit)), rw(pda("s1v1_owner", exit)), sign(wallet, true), ro(token), ro(system), ro(rent)]
                + provider(mintString) + [rw(book)])
        case let .completeWithdrawal(hillString, mintString, depositID, requestID, week, refresh):
            if refresh { try refreshRate(mintString) }
            let req = try request(lot(depositID), requestID), exit = try pda("s1v1_exit", req)
            let hill = try decodePublicKey(hillString), mint = try decodePublicKey(mintString), book = try funding(hill, mint, week)
            try createATA(mint)
            try add("6b6286834a78ae79", [rw(city), rw(hill), rw(exit), rw(req), rw(pda("s1v1_asset", mint)),
                rw(pda("s1v1_custody", exit)), rw(pda("s1v1_owner", exit)), rw(pda("s1v1_earnings", mint)), rw(ata(mint)), sign(wallet), ro(token)]
                + provider(mintString) + [rw(book)])
        case let .cashClaim(mintString, leaves, single):
            let mint = try decodePublicKey(mintString)
            guard mint == usdc || mint == stage1Cash || stage1Providers[mintString] != nil || testPool?.mint == mintString, (1...4).contains(leaves.count) else { throw ValidationError.rejected }
            try createATA(mint)
            var args = wallet + stage1LE(UInt32(leaves.count)), remaining: [Stage1Meta] = [], sets = Set<Data>(), total: UInt64 = 0
            for item in leaves {
                guard item.cap > 0, item.auditHash.count == 32 else { throw ValidationError.rejected }
                let sum = total.addingReportingOverflow(item.leaf.amount)
                guard !sum.overflow else { throw ValidationError.rejected }; total = sum.partialValue
                args += try claimBytes(item.leaf) + stage1LE(item.cap) + stage1LE(item.frozenAt) + item.auditHash
                let claim = try pda("s1v1_claims", decodePublicKey(item.leaf.hill), mint, stage1LE(item.leaf.week))
                guard sets.insert(claim).inserted else { throw ValidationError.rejected }; remaining.append(rw(claim))
            }
            if single {
                guard leaves.count == 1 else { throw ValidationError.rejected }
                args = args.subdata(in: 36..<40) + args.subdata(in: 0..<32) + args.subdata(in: 40..<args.count)
                try add("c09b05588b5182fd", args, [ro(city), rw(pda("s1v1_asset", mint)), remaining[0], ro(registration), rw(pda("s1v1_earnings", mint)), rw(ata(mint)), ro(token)])
            } else {
                try add("b7ea102a587362ad", args, [ro(city), rw(pda("s1v1_asset", mint)), ro(registration), rw(pda("s1v1_earnings", mint)), rw(ata(mint)), ro(token)] + remaining)
            }
        case let .dungClaim(leaves, single):
            guard (1...4).contains(leaves.count) else { throw ValidationError.rejected }
            try createATA(dungMintKey)
            var args = wallet + stage1LE(UInt32(leaves.count)), remaining: [Stage1Meta] = [], sets = Set<Data>(), total: UInt64 = 0
            for item in leaves {
                guard item.role <= 1 else { throw ValidationError.rejected }
                let sum = total.addingReportingOverflow(item.leaf.amount)
                guard !sum.overflow else { throw ValidationError.rejected }; total = sum.partialValue
                args += try claimBytes(item.leaf)
                let dung = try pda("s1v1_dung", decodePublicKey(item.leaf.hill), stage1LE(item.leaf.week))
                let claim = try pda("s1v1_dung_claims", dung, Data([item.role]))
                guard sets.insert(claim).inserted else { throw ValidationError.rejected }; remaining += [rw(dung), rw(claim)]
            }
            if single {
                guard leaves.count == 1 else { throw ValidationError.rejected }
                args = args.subdata(in: 36..<40) + args.subdata(in: 0..<32) + args.subdata(in: 40..<args.count)
                try add("ba1c8b56d8a8f876", args, [ro(city)] + remaining + [rw(pda("s1v1_dung_state")), ro(registration), ro(pda("program_config")),
                    rw(dungMintKey), ro(pda("dung_mint_auth")), rw(ata(dungMintKey)), ro(token)])
            } else {
                try add("b784485ccc8d595a", args, [ro(city), rw(pda("s1v1_dung_state")), ro(registration), ro(pda("program_config")),
                    rw(dungMintKey), ro(pda("dung_mint_auth")), rw(ata(dungMintKey)), ro(token)] + remaining)
            }
        }
        guard message.instructions.count == expected.count else { throw ValidationError.rejected }
        var signers: Set<Data> = [fee], writable: Set<Data> = [fee]
        for (index, instruction) in expected.enumerated() {
            try requireInstruction(message, at: index, program: instruction.program, data: instruction.data,
                                   accounts: instruction.keys.map { .exact($0.key) })
            for meta in instruction.keys {
                if meta.signer { signers.insert(meta.key) }
                if meta.writable { writable.insert(meta.key) }
            }
        }
        try requireGlobalRoles(message, signers: signers, writable: writable)
    }
}

/// Release-pinned policy for the two wallet-signing Balance actions shipped by
/// the native app. This firewall runs before Privy or the DEBUG wallet sees the
/// bytes. The backend independently rebuilds and byte-compares the message at
/// submission, so neither boundary is trusted alone.
enum BalanceTransactionFirewall {
    enum ValidationError: LocalizedError {
        case rejected

        var errorDescription: String? {
            "Prepared Balance transaction does not match the requested action"
        }
    }

    // Current production app talks to the pinned devnet release. A key,
    // program, mint, or treasury rotation therefore requires an app release;
    // an unexpected rotation fails closed instead of broadening authority.
    static let boulderProgram = "EVjP2Vdz9buHNphywPhoybf213poa8EiSW6FGbXWFqYH"
    static let tokenProgram = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
    static let associatedTokenProgram = "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL"
    static let systemProgram = "11111111111111111111111111111111"
    static let rentSysvar = "SysvarRent111111111111111111111111111111111"
    static let feePayer = "9h6UJdZqUPNnShaUHkSoxvEeZ7gBeNxzXGQcShhBnzEP"
    static let backendAuthority = "CJz8PUyNVvLuXJvjsYXgSKD9utZVP2XoTEZq6M973Gha"
    static let calMint = "4bxTCxEQp993cXs5nqhfWthRCPSTDv5K6PMgsfunEaJh"
    static let dungMint = "CqDFJWLpr49tB8xjHegy5JR5jwMCfmhicjuWawtKLeCk"
    static let protocolTreasury = "9wkFkPSH9eL1XdifxzM7ASfqyVtSZWAuLGUXTx5ijwPr"
    // Stage 1 devnet test USDC: the devnet city's admitted cash asset (6 decimals, legacy token program).
    static let stage1CashMint = "932CwEMTWHDY1BEkV66DKDgngeEypU3JmybWBu4vMh1e"

    private static let initializeVaultLPMint = Data([
        0x61, 0xc2, 0x88, 0xee, 0xf6, 0xff, 0x47, 0x81,
    ])
    private static let initializeVaultCALEscrow = Data([
        0x4d, 0xb2, 0xd0, 0x97, 0xd8, 0x22, 0x1b, 0xd0,
    ])
    private static let initializeVaultPositionLP = Data([
        0x14, 0xc0, 0xcc, 0xb7, 0xe4, 0xbe, 0xce, 0xf4,
    ])
    private static let stakeCALInVault = Data([
        0x93, 0x96, 0x5b, 0x0c, 0x13, 0xfa, 0xbd, 0x6a,
    ])
    private static let collectStakeRewardsFor = Data([
        0xdc, 0x76, 0xb7, 0xf5, 0xd1, 0xed, 0x42, 0x3d,
    ])
    private static let unstakeCALFromVault = Data([
        0x8f, 0x48, 0x92, 0x6c, 0xa6, 0x36, 0x2c, 0x10,
    ])

    static func validate(transactionB64: String, intent: BalanceTransactionIntent,
                         lookupTables: [SolanaTransaction.ResolvedLookupTable] = [], stage1TestPool: Stage1TestPool? = nil) throws {
        if case let .stage1(action, wallet) = intent {
            let message = try SolanaTransaction.parseStage1Message(transactionB64: transactionB64, owner: decodePublicKey(wallet), tables: lookupTables)
            if message.staticKeyCount > 0 {
                switch action {
                case .cashClaim(_, _, true), .dungClaim(_, true): break
                default: throw ValidationError.rejected
                }
            }
            try validateStage1(message, intent: action, wallet: wallet, testPool: stage1TestPool)
            try requireEveryStaticKeyIsUsed(message)
            return
        }
        let message = try SolanaTransaction.parseLegacyMessage(transactionB64: transactionB64)
        guard let values = intent.values else { throw ValidationError.rejected }
        guard values.amount > 0 else { throw ValidationError.rejected }
        let context = try Context(vaultId: values.vaultId, walletAddress: values.wallet)
        guard message.feePayer == context.feePayer else { throw ValidationError.rejected }

        switch values.operation {
        case .stake:
            try validateStake(message, amount: values.amount, context: context)
        case .unstake:
            try validateUnstake(message, amount: values.amount, context: context)
        }
        try requireEveryStaticKeyIsUsed(message)
    }

    private static func validateStake(
        _ message: SolanaTransaction.LegacyMessage,
        amount: UInt64,
        context: Context
    ) throws {
        var cursor = 0

        if hasData(message, at: cursor, initializeVaultLPMint) {
            try requireInstruction(
                message,
                at: cursor,
                program: context.program,
                data: initializeVaultLPMint,
                accounts: [
                    context.vault,
                    context.vaultLPMint,
                    .exact(context.feePayer),
                    .exact(context.tokenProgram),
                    .exact(context.systemProgram),
                    .exact(context.rentSysvar),
                ]
            )
            cursor += 1
        }

        if hasData(message, at: cursor, initializeVaultCALEscrow) {
            try requireInstruction(
                message,
                at: cursor,
                program: context.program,
                data: initializeVaultCALEscrow,
                accounts: [
                    context.vault,
                    context.programConfig,
                    context.vaultCALEscrow,
                    .exact(context.calMint),
                    .exact(context.feePayer),
                    .exact(context.tokenProgram),
                    .exact(context.systemProgram),
                    .exact(context.rentSysvar),
                ]
            )
            cursor += 1
        }

        try requireInstruction(
            message,
            at: cursor,
            program: context.program,
            data: initializeVaultPositionLP,
            accounts: [
                context.vault,
                .exact(context.wallet),
                context.vaultStake,
                context.vaultLPMint,
                context.positionLP,
                .exact(context.backendAuthority),
                .exact(context.tokenProgram),
                .exact(context.systemProgram),
            ]
        )
        cursor += 1

        let stakeData = stakeCALInVault + littleEndian(amount)
        let stakeInstruction = try requireInstruction(
            message,
            at: cursor,
            program: context.program,
            data: stakeData,
            accounts: [
                context.vault,
                context.vaultStake,
                context.vaultActivation,
                context.programConfig,
                .exact(context.backendAuthority),
                .exact(context.wallet),
                context.walletCALAccount,
                context.vaultCALEscrow,
                context.vaultLPMint,
                context.positionLP,
                .exact(context.tokenProgram),
                .exact(context.systemProgram),
            ]
        )
        cursor += 1
        guard cursor == message.instructions.count else { throw ValidationError.rejected }

        let accounts = instructionAccounts(stakeInstruction, in: message)
        let expectedSigners: Set<Data> = [
            context.feePayer, context.backendAuthority, context.wallet,
        ]
        let expectedWritable: Set<Data> = [
            context.feePayer,
            context.backendAuthority,
            context.wallet,
            accounts[0], // vault
            accounts[1], // VaultStake
            accounts[6], // rider CAL ATA
            accounts[7], // CAL escrow
            accounts[8], // LP mint
            accounts[9], // sealed position LP account
        ]
        try requireGlobalRoles(
            message,
            signers: expectedSigners,
            writable: expectedWritable
        )
    }

    private static func validateUnstake(
        _ message: SolanaTransaction.LegacyMessage,
        amount: UInt64,
        context: Context
    ) throws {
        var cursor = 0
        var createdDungAccount = false
        var collectInstruction: SolanaTransaction.LegacyInstruction?

        if isATAInstruction(message, at: cursor, mint: context.dungMint) {
            _ = try requireCreateATA(
                message,
                at: cursor,
                owner: context.wallet,
                mint: context.dungMint,
                account: context.walletDungAccount,
                context: context
            )
            createdDungAccount = true
            cursor += 1
        }

        if hasInstruction(
            message,
            at: cursor,
            program: context.program,
            data: collectStakeRewardsFor
        ) {
            collectInstruction = try requireInstruction(
                message,
                at: cursor,
                program: context.program,
                data: collectStakeRewardsFor,
                accounts: [
                    context.vault,
                    context.vaultStake,
                    context.vaultActivation,
                    .exact(context.wallet),
                    .exact(context.feePayer),
                    .exact(context.dungMint),
                    context.walletDungAccount,
                    .exact(context.protocolTreasury),
                    context.dungMintState,
                    context.programConfig,
                    context.dungMintAuthority,
                    .exact(context.tokenProgram),
                ]
            )
            cursor += 1
        } else if createdDungAccount {
            throw ValidationError.rejected
        }

        if isATAInstruction(message, at: cursor, mint: context.calMint) {
            _ = try requireCreateATA(
                message,
                at: cursor,
                owner: context.wallet,
                mint: context.calMint,
                account: context.walletCALAccount,
                context: context
            )
            cursor += 1
        }

        let unstakeInstruction = try requireInstruction(
            message,
            at: cursor,
            program: context.program,
            data: unstakeCALFromVault + littleEndian(amount),
            accounts: [
                context.vault,
                context.vaultStake,
                context.vaultActivation,
                context.programConfig,
                .exact(context.wallet),
                context.walletCALAccount,
                context.vaultCALEscrow,
                .exact(context.calMint),
                context.vaultLPMint,
                context.positionLP,
                .exact(context.tokenProgram),
            ]
        )
        cursor += 1
        guard cursor == message.instructions.count else { throw ValidationError.rejected }

        let accounts = instructionAccounts(unstakeInstruction, in: message)
        var expectedWritable: Set<Data> = [
            context.feePayer,
            context.wallet,
            accounts[0], // vault
            accounts[1], // VaultStake
            accounts[5], // rider CAL ATA
            accounts[6], // CAL escrow
            accounts[7], // CAL mint
            accounts[8], // LP mint
            accounts[9], // sealed position LP account
        ]
        if let collectInstruction {
            let collectAccounts = instructionAccounts(collectInstruction, in: message)
            expectedWritable.formUnion([
                collectAccounts[5], // DUNG mint
                collectAccounts[6], // rider DUNG ATA
                collectAccounts[7], // protocol treasury
                collectAccounts[8], // DUNG mint state
            ])
        }
        try requireGlobalRoles(
            message,
            signers: [context.feePayer, context.wallet],
            writable: expectedWritable
        )
    }

    @discardableResult
    private static func requireCreateATA(
        _ message: SolanaTransaction.LegacyMessage,
        at index: Int,
        owner: Data,
        mint: Data,
        account: AccountExpectation,
        context: Context
    ) throws -> SolanaTransaction.LegacyInstruction {
        try requireInstruction(
            message,
            at: index,
            program: context.associatedTokenProgram,
            data: Data(),
            accounts: [
                .exact(context.feePayer),
                account,
                .exact(owner),
                .exact(mint),
                .exact(context.systemProgram),
                .exact(context.tokenProgram),
                .exact(context.rentSysvar),
            ]
        )
    }

    @discardableResult
    private static func requireInstruction(
        _ message: SolanaTransaction.LegacyMessage,
        at index: Int,
        program: Data,
        data: Data,
        accounts expectedAccounts: [AccountExpectation]
    ) throws -> SolanaTransaction.LegacyInstruction {
        guard message.instructions.indices.contains(index) else {
            throw ValidationError.rejected
        }
        let instruction = message.instructions[index]
        guard instruction.programID == program,
              instruction.data == data,
              instruction.accountIndices.count == expectedAccounts.count
        else {
            throw ValidationError.rejected
        }

        for (accountIndex, expected) in zip(
            instruction.accountIndices,
            expectedAccounts
        ) {
            guard expected.matches(message.accountKeys[accountIndex]) else {
                throw ValidationError.rejected
            }
        }
        return instruction
    }

    private static func requireGlobalRoles(
        _ message: SolanaTransaction.LegacyMessage,
        signers expectedSigners: Set<Data>,
        writable expectedWritable: Set<Data>
    ) throws {
        let actualSigners = Set(
            message.accountKeys.indices.compactMap {
                message.isSigner($0) ? message.accountKeys[$0] : nil
            }
        )
        let actualWritable = Set(
            message.accountKeys.indices.compactMap {
                message.isWritable($0) ? message.accountKeys[$0] : nil
            }
        )
        guard actualSigners == expectedSigners,
              actualWritable == expectedWritable
        else {
            throw ValidationError.rejected
        }
    }

    private static func requireEveryStaticKeyIsUsed(
        _ message: SolanaTransaction.LegacyMessage
    ) throws {
        // The fee payer is consumed by the message header even when no
        // instruction repeats it as an account.
        var usedIndices: Set<Int> = [0]
        for instruction in message.instructions {
            guard let programIndex = message.accountKeys.firstIndex(of: instruction.programID) else {
                throw ValidationError.rejected
            }
            usedIndices.insert(programIndex)
            usedIndices.formUnion(instruction.accountIndices)
        }
        guard usedIndices == Set(message.accountKeys.indices) else {
            throw ValidationError.rejected
        }
    }

    private static func instructionAccounts(
        _ instruction: SolanaTransaction.LegacyInstruction,
        in message: SolanaTransaction.LegacyMessage
    ) -> [Data] {
        instruction.accountIndices.map { message.accountKeys[$0] }
    }

    private static func hasData(
        _ message: SolanaTransaction.LegacyMessage,
        at index: Int,
        _ data: Data
    ) -> Bool {
        message.instructions.indices.contains(index)
            && message.instructions[index].data == data
    }

    private static func hasInstruction(
        _ message: SolanaTransaction.LegacyMessage,
        at index: Int,
        program: Data,
        data: Data
    ) -> Bool {
        message.instructions.indices.contains(index)
            && message.instructions[index].programID == program
            && message.instructions[index].data == data
    }

    private static func isATAInstruction(
        _ message: SolanaTransaction.LegacyMessage,
        at index: Int,
        mint: Data
    ) -> Bool {
        guard message.instructions.indices.contains(index) else { return false }
        let instruction = message.instructions[index]
        guard instruction.programID == (try? decodePublicKey(associatedTokenProgram)),
              instruction.data.isEmpty,
              instruction.accountIndices.count == 7
        else {
            return false
        }
        return message.accountKeys[instruction.accountIndices[3]] == mint
    }

    /// Base58 public-key decoding is kept here so signing policy does not add a
    /// broad Solana SDK dependency. Tests round-trip every pinned key.
    static func decodePublicKey(_ value: String) throws -> Data {
        let alphabet = Array(
            "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
        )
        var bytes: [UInt8] = []
        for character in value {
            guard let digit = alphabet.firstIndex(of: character) else {
                throw ValidationError.rejected
            }
            var carry = digit
            for index in bytes.indices.reversed() {
                let product = Int(bytes[index]) * 58 + carry
                bytes[index] = UInt8(product & 0xFF)
                carry = product >> 8
            }
            while carry > 0 {
                bytes.insert(UInt8(carry & 0xFF), at: 0)
                carry >>= 8
            }
        }
        for _ in value.prefix(while: { $0 == "1" }) {
            bytes.insert(0, at: 0)
        }
        guard bytes.count == 32 else { throw ValidationError.rejected }
        return Data(bytes)
    }

    private static func littleEndian(_ value: UInt64) -> Data {
        var encoded = value.littleEndian
        return Data(bytes: &encoded, count: MemoryLayout<UInt64>.size)
    }

    private static func matchesProgramAddress(
        _ address: Data,
        seeds: [Data],
        program: Data
    ) -> Bool {
        SolanaProgramAddress.matchesCanonical(
            address,
            seeds: seeds,
            program: program
        )
    }

    private enum AccountExpectation {
        case exact(Data)
        case programAddress(seeds: [Data], program: Data)

        func matches(_ address: Data) -> Bool {
            switch self {
            case let .exact(expected):
                return address == expected
            case let .programAddress(seeds, program):
                return BalanceTransactionFirewall.matchesProgramAddress(
                    address,
                    seeds: seeds,
                    program: program
                )
            }
        }
    }

    private struct Context {
        let vaultID: Data
        let wallet: Data
        let program: Data
        let tokenProgram: Data
        let associatedTokenProgram: Data
        let systemProgram: Data
        let rentSysvar: Data
        let feePayer: Data
        let backendAuthority: Data
        let calMint: Data
        let dungMint: Data
        let protocolTreasury: Data

        init(vaultId: Int, walletAddress: String) throws {
            guard let exactVaultID = UInt64(exactly: vaultId) else {
                throw ValidationError.rejected
            }
            vaultID = BalanceTransactionFirewall.littleEndian(exactVaultID)
            wallet = try BalanceTransactionFirewall.decodePublicKey(walletAddress)
            program = try BalanceTransactionFirewall.decodePublicKey(boulderProgram)
            tokenProgram = try BalanceTransactionFirewall.decodePublicKey(
                BalanceTransactionFirewall.tokenProgram
            )
            associatedTokenProgram = try BalanceTransactionFirewall.decodePublicKey(
                BalanceTransactionFirewall.associatedTokenProgram
            )
            systemProgram = try BalanceTransactionFirewall.decodePublicKey(
                BalanceTransactionFirewall.systemProgram
            )
            rentSysvar = try BalanceTransactionFirewall.decodePublicKey(
                BalanceTransactionFirewall.rentSysvar
            )
            feePayer = try BalanceTransactionFirewall.decodePublicKey(
                BalanceTransactionFirewall.feePayer
            )
            backendAuthority = try BalanceTransactionFirewall.decodePublicKey(
                BalanceTransactionFirewall.backendAuthority
            )
            calMint = try BalanceTransactionFirewall.decodePublicKey(
                BalanceTransactionFirewall.calMint
            )
            dungMint = try BalanceTransactionFirewall.decodePublicKey(
                BalanceTransactionFirewall.dungMint
            )
            protocolTreasury = try BalanceTransactionFirewall.decodePublicKey(
                BalanceTransactionFirewall.protocolTreasury
            )

            let forbiddenWallets: Set<Data> = [
                program,
                tokenProgram,
                associatedTokenProgram,
                systemProgram,
                rentSysvar,
                feePayer,
                backendAuthority,
                calMint,
                dungMint,
                protocolTreasury,
            ]
            guard !forbiddenWallets.contains(wallet) else {
                throw ValidationError.rejected
            }
        }

        var vault: AccountExpectation {
            pda("vault", vaultID)
        }

        var vaultStake: AccountExpectation {
            pda("vault_stake", wallet, vaultID)
        }

        var vaultActivation: AccountExpectation {
            pda("vault_activation", vaultID)
        }

        var programConfig: AccountExpectation {
            pda("program_config")
        }

        var vaultCALEscrow: AccountExpectation {
            pda("vault_cal_escrow", vaultID)
        }

        var vaultLPMint: AccountExpectation {
            pda("vault_lp", vaultID)
        }

        var positionLP: AccountExpectation {
            pda("vault_position_lp", wallet, vaultID)
        }

        var walletCALAccount: AccountExpectation {
            ata(owner: wallet, mint: calMint)
        }

        var walletDungAccount: AccountExpectation {
            ata(owner: wallet, mint: dungMint)
        }

        var dungMintState: AccountExpectation {
            pda("dung_mint_state")
        }

        var dungMintAuthority: AccountExpectation {
            pda("dung_mint_auth")
        }

        private func pda(_ stringSeed: String, _ remainingSeeds: Data...) -> AccountExpectation {
            .programAddress(
                seeds: [Data(stringSeed.utf8)] + remainingSeeds,
                program: program
            )
        }

        private func ata(owner: Data, mint: Data) -> AccountExpectation {
            .programAddress(
                seeds: [owner, tokenProgram, mint],
                program: associatedTokenProgram
            )
        }
    }
}
