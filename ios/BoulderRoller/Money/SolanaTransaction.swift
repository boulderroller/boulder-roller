import CryptoKit
import Foundation

/// Minimal Solana legacy wire-format handling for backend-prepared Balance
/// transactions. Versioned messages deliberately fail closed until the app
/// can resolve and validate address lookup tables.
enum SolanaTransaction {
    enum SigningError: LocalizedError {
        case malformed
        case signerNotInAccounts

        var errorDescription: String? {
            switch self {
            case .malformed: return "Prepared transaction is malformed"
            case .signerNotInAccounts: return "This account is not a signer on the prepared transaction"
            }
        }
    }

    struct LegacyInstruction {
        let programID: Data
        let accountIndices: [Int]
        let data: Data
    }

    struct LegacyMessage {
        let signatureCount: Int
        let requiredSigners: Int
        let readonlySigned: Int
        let readonlyUnsigned: Int
        let accountKeys: [Data]
        let instructions: [LegacyInstruction]
        var staticKeyCount: Int = 0
        var loadedWritableCount: Int = 0

        var feePayer: Data { accountKeys[0] }

        func isSigner(_ index: Int) -> Bool {
            index >= 0 && index < requiredSigners
        }

        func isWritable(_ index: Int) -> Bool {
            guard index >= 0 && index < accountKeys.count else { return false }
            if index < requiredSigners {
                return index < requiredSigners - readonlySigned
            }
            if staticKeyCount > 0 {
                return index < staticKeyCount ? index < staticKeyCount - readonlyUnsigned : index < staticKeyCount + loadedWritableCount
            }
            return index < accountKeys.count - readonlyUnsigned
        }
    }

    static func parseLegacyMessage(transactionB64: String) throws -> LegacyMessage {
        guard let wire = Data(base64Encoded: transactionB64) else {
            throw SigningError.malformed
        }
        var cursor = 0
        let signatureCount = try readShortVecLength(wire, &cursor)
        guard signatureCount > 0,
              signatureCount <= 255,
              cursor + signatureCount * 64 <= wire.count
        else {
            throw SigningError.malformed
        }
        cursor += signatureCount * 64

        let message = wire.subdata(in: cursor..<wire.count)
        guard !message.isEmpty, message[message.startIndex] & 0x80 == 0 else {
            throw SigningError.malformed
        }

        var messageCursor = 0
        guard messageCursor + 3 <= message.count else { throw SigningError.malformed }
        let requiredSigners = Int(message[messageCursor])
        let readonlySigned = Int(message[messageCursor + 1])
        let readonlyUnsigned = Int(message[messageCursor + 2])
        messageCursor += 3

        let keyCount = try readShortVecLength(message, &messageCursor)
        guard requiredSigners > 0,
              signatureCount == requiredSigners,
              keyCount > 0,
              requiredSigners <= keyCount,
              readonlySigned <= requiredSigners,
              readonlyUnsigned <= keyCount - requiredSigners,
              messageCursor + keyCount * 32 + 32 <= message.count
        else {
            throw SigningError.malformed
        }

        var accountKeys: [Data] = []
        accountKeys.reserveCapacity(keyCount)
        for _ in 0..<keyCount {
            accountKeys.append(message.subdata(in: messageCursor..<(messageCursor + 32)))
            messageCursor += 32
        }
        guard Set(accountKeys).count == accountKeys.count else {
            throw SigningError.malformed
        }

        messageCursor += 32 // recent blockhash
        let instructionCount = try readShortVecLength(message, &messageCursor)
        var instructions: [LegacyInstruction] = []
        instructions.reserveCapacity(instructionCount)
        for _ in 0..<instructionCount {
            guard messageCursor < message.count else { throw SigningError.malformed }
            let programIndex = Int(message[messageCursor])
            messageCursor += 1
            guard programIndex < accountKeys.count else { throw SigningError.malformed }

            let accountCount = try readShortVecLength(message, &messageCursor)
            guard messageCursor + accountCount <= message.count else {
                throw SigningError.malformed
            }
            let accountIndices = (0..<accountCount).map {
                Int(message[messageCursor + $0])
            }
            guard accountIndices.allSatisfy({ $0 < accountKeys.count }) else {
                throw SigningError.malformed
            }
            messageCursor += accountCount

            let dataCount = try readShortVecLength(message, &messageCursor)
            guard messageCursor + dataCount <= message.count else {
                throw SigningError.malformed
            }
            let instructionData = message.subdata(
                in: messageCursor..<(messageCursor + dataCount)
            )
            messageCursor += dataCount
            instructions.append(
                LegacyInstruction(
                    programID: accountKeys[programIndex],
                    accountIndices: accountIndices,
                    data: instructionData
                )
            )
        }
        guard messageCursor == message.count else { throw SigningError.malformed }

        return LegacyMessage(
            signatureCount: signatureCount,
            requiredSigners: requiredSigners,
            readonlySigned: readonlySigned,
            readonlyUnsigned: readonlyUnsigned,
            accountKeys: accountKeys,
            instructions: instructions
        )
    }

    /// Supplied by the caller's independent RPC lookup, never by prepare JSON.
    struct ResolvedLookupTable {
        let address: Data
        let authority: Data
        let active: Bool
        let addresses: [Data]
    }

    static func parseStage1Message(transactionB64: String, owner: Data,
                                   tables: [ResolvedLookupTable]) throws -> LegacyMessage {
        guard let wire = Data(base64Encoded: transactionB64), wire.count <= 1232 else { throw SigningError.malformed }
        var cursor = 0
        let signatures = try readShortVecLength(wire, &cursor)
        guard signatures > 0, cursor + signatures * 64 < wire.count else { throw SigningError.malformed }
        cursor += signatures * 64
        if wire[cursor] & 0x80 == 0 { return try parseLegacyMessage(transactionB64: transactionB64) }
        guard wire[cursor] == 0x80, cursor + 4 < wire.count else { throw SigningError.malformed }
        cursor += 1
        let required = Int(wire[cursor]), readSigned = Int(wire[cursor + 1]), readUnsigned = Int(wire[cursor + 2])
        cursor += 3
        let staticCount = try readShortVecLength(wire, &cursor)
        guard signatures == required, required <= staticCount, readSigned <= required,
              readUnsigned <= staticCount - required, cursor + staticCount * 32 + 32 <= wire.count else { throw SigningError.malformed }
        var keys: [Data] = []
        for _ in 0..<staticCount { keys.append(wire.subdata(in: cursor..<cursor + 32)); cursor += 32 }
        cursor += 32
        let count = try readShortVecLength(wire, &cursor)
        var raw: [(Int, [Int], Data)] = []
        for _ in 0..<count {
            guard cursor < wire.count else { throw SigningError.malformed }
            let program = Int(wire[cursor]); cursor += 1
            let n = try readShortVecLength(wire, &cursor)
            guard program < staticCount, cursor + n <= wire.count else { throw SigningError.malformed }
            let indices = wire.subdata(in: cursor..<cursor + n).map(Int.init); cursor += n
            let length = try readShortVecLength(wire, &cursor)
            guard cursor + length <= wire.count else { throw SigningError.malformed }
            raw.append((program, indices, wire.subdata(in: cursor..<cursor + length))); cursor += length
        }
        guard try readShortVecLength(wire, &cursor) == 1, cursor + 32 <= wire.count else { throw SigningError.malformed }
        let tableKey = wire.subdata(in: cursor..<cursor + 32); cursor += 32
        guard tables.count == 1, let table = tables.first, table.address == tableKey, table.authority == owner,
              table.active, table.addresses.allSatisfy({ $0.count == 32 }) else { throw SigningError.malformed }
        let writes = try readShortVecLength(wire, &cursor)
        guard cursor + writes <= wire.count else { throw SigningError.malformed }
        let writable = wire.subdata(in: cursor..<cursor + writes).map(Int.init); cursor += writes
        let reads = try readShortVecLength(wire, &cursor)
        guard cursor + reads == wire.count else { throw SigningError.malformed }
        let readonly = wire.subdata(in: cursor..<cursor + reads).map(Int.init)
        guard (writable + readonly).allSatisfy({ $0 < table.addresses.count }) else { throw SigningError.malformed }
        keys += (writable + readonly).map { table.addresses[$0] }
        guard Set(keys).count == keys.count, raw.allSatisfy({ $0.1.allSatisfy({ $0 < keys.count }) }) else { throw SigningError.malformed }
        return LegacyMessage(signatureCount: signatures, requiredSigners: required, readonlySigned: readSigned,
            readonlyUnsigned: readUnsigned, accountKeys: keys,
            instructions: raw.map { LegacyInstruction(programID: keys[$0.0], accountIndices: $0.1, data: $0.2) },
            staticKeyCount: staticCount, loadedWritableCount: writes)
    }

    /// Place the rider's ed25519 signature at its required-signer position.
    /// Existing backend signatures are preserved byte for byte.
    static func partiallySign(
        transactionB64: String,
        privateKey: Curve25519.Signing.PrivateKey
    ) throws -> String {
        guard let wire = Data(base64Encoded: transactionB64) else {
            throw SigningError.malformed
        }
        var cursor = 0
        let signatureCount = try readShortVecLength(wire, &cursor)
        var signatures: [Data] = []
        signatures.reserveCapacity(signatureCount)
        for _ in 0..<signatureCount {
            guard cursor + 64 <= wire.count else { throw SigningError.malformed }
            signatures.append(wire.subdata(in: cursor..<(cursor + 64)))
            cursor += 64
        }

        let message = wire.subdata(in: cursor..<wire.count)
        var messageCursor = 0
        guard message.count > 3, message[message.startIndex] & 0x80 == 0 || message[message.startIndex] == 0x80 else {
            throw SigningError.malformed
        }
        if message[message.startIndex] == 0x80 { messageCursor += 1 }
        let requiredSigners = Int(message[messageCursor])
        messageCursor += 3
        let keyCount = try readShortVecLength(message, &messageCursor)
        guard signatureCount == requiredSigners,
              message.count >= messageCursor + keyCount * 32,
              requiredSigners <= keyCount
        else {
            throw SigningError.malformed
        }

        let publicKey = privateKey.publicKey.rawRepresentation
        var signerIndex: Int?
        for index in 0..<requiredSigners {
            let start = messageCursor + index * 32
            let key = message.subdata(in: start..<(start + 32))
            if key == publicKey {
                signerIndex = index
                break
            }
        }
        guard let signerIndex else { throw SigningError.signerNotInAccounts }
        signatures[signerIndex] = try privateKey.signature(for: message)

        var output = Data()
        output.append(shortVec(requiredSigners))
        for signature in signatures { output.append(signature) }
        output.append(message)
        return output.base64EncodedString()
    }

    private static func readShortVecLength(_ data: Data, _ cursor: inout Int) throws -> Int {
        var length = 0
        var shift = 0
        while true {
            guard cursor < data.count, shift < 21 else { throw SigningError.malformed }
            let byte = data[data.startIndex + cursor]
            cursor += 1
            length |= Int(byte & 0x7F) << shift
            if byte & 0x80 == 0 {
                guard shift == 0 || byte != 0 else { throw SigningError.malformed }
                return length
            }
            shift += 7
        }
    }

    private static func shortVec(_ value: Int) -> Data {
        var output = Data()
        var remaining = value
        repeat {
            var byte = UInt8(remaining & 0x7F)
            remaining >>= 7
            if remaining > 0 { byte |= 0x80 }
            output.append(byte)
        } while remaining > 0
        return output
    }
}
